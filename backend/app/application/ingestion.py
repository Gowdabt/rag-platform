from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.db.models import (
    ChunkEmbedding,
    ContentObject,
    DataSource,
    Document,
    DocumentChunk,
    DocumentVersion,
    EmbeddingProfile,
    IngestionJob,
    SourceSubscription,
)
from app.application.audit import write_audit
from app.application.authz import (
    apply_acl_patch,
    assert_workspace_access,
    authorized_document_ids,
    can_read_document,
    can_share_document,
    inherit_acl,
    merge_acl,
    owner_acl,
    resolve_share_user_ids,
    resolve_upload_acl,
)
from app.application.authz_epoch import persist_authz_bump
from app.application.content_address import pipeline_fingerprint
from app.application.factory import ProviderFactory
from app.config.models import PlatformSettings
from app.core.context import RequestContext
from app.core.errors import ForbiddenError, NotFoundError, ValidationFailedError
from app.domain.types import VectorRecord


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class IngestionService:
    def __init__(self, session: AsyncSession, settings: PlatformSettings, ctx: RequestContext):
        self.session = session
        self.settings = settings
        self.ctx = ctx
        self.factory = ProviderFactory(settings, ctx)

    def _store(self):
        return self.factory.create("storage", config=self.settings.storage, ctx=self.ctx)

    def _parser(self):
        return self.factory.create("parser", config=self.settings.parser, ctx=self.ctx)

    def _chunker(self):
        return self.factory.create(
            "chunker", self.settings.chunking.strategy, config=self.settings.chunking, ctx=self.ctx
        )

    def _embedder(self):
        return self.factory.create("embedding", config=self.settings.embedding, ctx=self.ctx)

    def _vectors(self):
        return self.factory.create(
            "vector_store", config=self.settings.vector_store, ctx=self.ctx, session=self.session
        )

    def _queue(self):
        return self.factory.create("queue", ctx=self.ctx)

    async def _lock_content(self, content_hash: str, fingerprint: str) -> None:
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:a), hashtext(:b))"),
            {"a": str(self.ctx.require_tenant()), "b": f"{content_hash}:{fingerprint}"},
        )

    async def _get_or_create_content_object(self, content: bytes, content_hash: str, mime_type: str) -> ContentObject:
        tenant = self.ctx.require_tenant()
        existing = await self.session.scalar(
            select(ContentObject).where(
                ContentObject.tenant_id == tenant,
                ContentObject.content_hash == content_hash,
            )
        )
        if existing:
            return existing
        key = f"{tenant}/cas/{content_hash[:2]}/{content_hash}"
        await self._store().put(key, content, content_type=mime_type)
        row = ContentObject(
            tenant_id=tenant,
            content_hash=content_hash,
            storage_key=key,
            mime_type=mime_type or "application/octet-stream",
            size_bytes=len(content),
            ref_count=0,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(row)
                await self.session.flush()
            return row
        except IntegrityError:
            found = await self.session.scalar(
                select(ContentObject).where(
                    ContentObject.tenant_id == tenant,
                    ContentObject.content_hash == content_hash,
                )
            )
            if found:
                return found
            raise

    async def _canonical_version(self, content_hash: str, fingerprint: str) -> DocumentVersion | None:
        return await self.session.scalar(
            select(DocumentVersion)
            .where(
                DocumentVersion.tenant_id == self.ctx.require_tenant(),
                DocumentVersion.content_hash == content_hash,
                DocumentVersion.pipeline_fingerprint == fingerprint,
                DocumentVersion.derived_from_version_id.is_(None),
                DocumentVersion.status.in_(("queued", "processing", "completed")),
            )
            .order_by(DocumentVersion.created_at.asc())
            .limit(1)
        )

    async def _document_by_source(self, source_id: UUID, source_file_id: str) -> Document | None:
        return await self.session.scalar(
            select(Document).where(
                Document.tenant_id == self.ctx.require_tenant(),
                Document.source_id == source_id,
                Document.source_file_id == source_file_id,
            )
        )

    async def _latest_version(self, document_id: UUID) -> DocumentVersion | None:
        return await self.session.scalar(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.version_number.desc())
        )

    async def _stamp_derived(self, canonical: DocumentVersion, status: str) -> None:
        values: dict = {"status": status}
        if status == "completed":
            values.update(
                parser_provider=canonical.parser_provider,
                parser_version=canonical.parser_version,
                chunker_strategy=canonical.chunker_strategy,
                chunker_version=canonical.chunker_version,
                ingested_at=datetime.now(UTC),
            )
        await self.session.execute(
            update(DocumentVersion)
            .where(DocumentVersion.derived_from_version_id == canonical.id)
            .values(**values)
        )

    async def _uploads_source(self, workspace_id: UUID) -> DataSource:
        source = await self.session.scalar(
            select(DataSource).where(
                DataSource.tenant_id == self.ctx.tenant_id,
                DataSource.workspace_id == workspace_id,
                DataSource.connector_type == "upload",
                DataSource.owner_user_id == self.ctx.user_id,
            )
        )
        if source:
            return source
        source = DataSource(
            tenant_id=self.ctx.tenant_id,
            workspace_id=workspace_id,
            owner_user_id=self.ctx.user_id,
            name="Uploads",
            connector_type="upload",
            status="connected",
        )
        self.session.add(source)
        await self.session.flush()
        return source

    def _document_acl(self, source: DataSource, acl: dict | None) -> tuple[UUID, dict]:
        owner_id = source.owner_user_id or self.ctx.user_id
        if owner_id is None:
            raise ValidationFailedError("Document owner is required")
        return owner_id, merge_acl(owner_acl(owner_id), acl)

    def _existing_document_acl(self, document: Document, source: DataSource, acl: dict | None) -> tuple[UUID, dict]:
        owner_id = document.owner_user_id or source.owner_user_id or self.ctx.user_id
        if owner_id is None:
            raise ValidationFailedError("Document owner is required")
        return owner_id, inherit_acl(document.acl, owner_id, acl)

    async def upload(
        self,
        *,
        filename: str,
        content: bytes,
        mime_type: str,
        workspace_id: UUID | None = None,
        acl: dict | None = None,
        visibility: str | None = None,
        allowed_roles: list[str] | None = None,
    ) -> dict:
        if not self.ctx.has("document:write"):
            raise ForbiddenError("Missing permission document:write")
        if len(content) > 50 * 1024 * 1024:
            raise ValidationFailedError("File too large")
        workspace_id = workspace_id or self.ctx.workspace_id
        if workspace_id is None:
            raise ValidationFailedError("workspace_id is required")
        await assert_workspace_access(self.session, self.ctx, workspace_id)
        source = await self._uploads_source(workspace_id)
        effective_acl = acl if acl is not None else resolve_upload_acl(
            self.ctx, visibility=visibility, allowed_roles=allowed_roles
        )
        return await self.ingest_content(
            source=source,
            source_file_id=filename,
            filename=filename,
            content=content,
            mime_type=mime_type,
            workspace_id=workspace_id,
            path=filename,
            acl=effective_acl,
        )

    def _mark_unchanged(self, document: Document, last: DocumentVersion, *, path: str | None, filename: str, revision: str | None) -> dict:
        document.path = path or document.path
        document.title = filename
        if revision:
            document.external_revision = revision
        document.external_status = "active"
        document.active_version_id = last.id
        return {
            "document_id": str(document.id),
            "version_id": str(last.id),
            "status": "unchanged",
            "version_new": False,
        }

    async def ingest_content(
        self,
        *,
        source: DataSource,
        source_file_id: str,
        filename: str,
        content: bytes,
        mime_type: str,
        workspace_id: UUID,
        subscription_id: UUID | None = None,
        revision: str | None = None,
        path: str | None = None,
        acl: dict | None = None,
    ) -> dict:
        tenant = self.ctx.require_tenant()
        content_hash = _hash_bytes(content)
        fingerprint = pipeline_fingerprint(self.settings)
        folder_id = None
        if subscription_id:
            sub = await self.session.get(SourceSubscription, subscription_id)
            if sub is not None:
                folder_id = sub.folder_id
        existing = await self._document_by_source(source.id, source_file_id)
        if existing:
            owner_id, effective_acl = self._existing_document_acl(existing, source, acl)
            last = await self._latest_version(existing.id)
            if last and last.content_hash == content_hash:
                payload = self._mark_unchanged(existing, last, path=path, filename=filename, revision=revision)
                existing.owner_user_id = existing.owner_user_id or owner_id
                existing.acl = effective_acl
                await self.session.flush()
                return payload

        await self._lock_content(content_hash, fingerprint)

        existing = await self._document_by_source(source.id, source_file_id)
        version_new = False
        if existing:
            owner_id, effective_acl = self._existing_document_acl(existing, source, acl)
            last = await self._latest_version(existing.id)
            if last and last.content_hash == content_hash:
                payload = self._mark_unchanged(existing, last, path=path, filename=filename, revision=revision)
                existing.owner_user_id = existing.owner_user_id or owner_id
                existing.acl = effective_acl
                await self.session.flush()
                return payload
            version_number = (last.version_number + 1) if last else 1
            document = existing
            version_new = True
            document.path = path or document.path
            document.title = filename
            document.external_status = "active"
            document.owner_user_id = document.owner_user_id or owner_id
            document.acl = effective_acl
            if revision:
                document.external_revision = revision
            if subscription_id:
                document.subscription_id = subscription_id
            if folder_id:
                document.folder_id = folder_id
        else:
            owner_id, effective_acl = self._document_acl(source, acl)
            document = Document(
                tenant_id=tenant,
                workspace_id=workspace_id,
                source_id=source.id,
                source_file_id=source_file_id,
                subscription_id=subscription_id,
                folder_id=folder_id,
                path=path or filename,
                title=filename,
                owner_user_id=owner_id,
                acl=effective_acl,
                external_revision=revision,
                external_status="active",
            )
            self.session.add(document)
            await self.session.flush()
            version_number = 1

        content_obj = await self._get_or_create_content_object(content, content_hash, mime_type)
        canonical = await self._canonical_version(content_hash, fingerprint)
        version = DocumentVersion(
            tenant_id=tenant,
            document_id=document.id,
            version_number=version_number,
            content_hash=content_hash,
            checksum=content_hash,
            mime_type=mime_type or "application/octet-stream",
            storage_key=content_obj.storage_key,
            size_bytes=len(content),
            status="queued",
            revision=revision,
            content_object_id=content_obj.id,
            pipeline_fingerprint=fingerprint,
            derived_from_version_id=canonical.id if canonical else None,
        )
        self.session.add(version)
        await self.session.flush()
        document.active_version_id = version.id
        content_obj.ref_count = (content_obj.ref_count or 0) + 1
        await self.session.flush()

        if canonical:
            if canonical.status in {"completed", "failed"}:
                await self._stamp_derived(canonical, canonical.status)
                version.status = canonical.status
            return {
                "document_id": str(document.id),
                "version_id": str(version.id),
                "status": "deduplicated",
                "canonical_version_id": str(canonical.id),
                "version_new": version_new,
            }

        job = IngestionJob(
            tenant_id=tenant,
            job_type="ingest",
            status="queued",
            idempotency_key=f"{tenant}:{source.id}:{source_file_id}:{content_hash}:{self.settings.embedding.model}",
            document_id=document.id,
            version_id=version.id,
            source_id=source.id,
        )
        self.session.add(job)
        await self.session.flush()
        await self._queue().enqueue(
            "ingest",
            {"job_id": str(job.id)},
            job_id=job.id,
            idempotency_key=job.idempotency_key,
        )
        return {
            "document_id": str(document.id),
            "version_id": str(version.id),
            "job_id": str(job.id),
            "status": "queued",
            "version_new": version_new,
        }

    async def process_job(self, job_id: UUID) -> None:
        job = await self.session.get(IngestionJob, job_id)
        if job is None:
            return
        if job.tenant_id != self.ctx.tenant_id:
            job.status = "failed"
            job.error = "Job tenant mismatch"
            return
        job.status = "processing"
        job.attempts += 1
        version = await self.session.get(DocumentVersion, job.version_id)
        document = await self.session.get(Document, job.document_id)
        if version is None or document is None:
            job.status = "failed"
            job.error = "Missing document version"
            return
        if document.tenant_id != self.ctx.tenant_id or version.tenant_id != self.ctx.tenant_id:
            job.status = "failed"
            job.error = "Job tenant mismatch"
            return
        if document.source_id:
            source = await self.session.get(DataSource, document.source_id)
            if source is None or source.tenant_id != self.ctx.tenant_id:
                job.status = "failed"
                job.error = "Source missing"
                return
        if version.derived_from_version_id:
            job.status = "completed"
            return
        # Capture scalars before begin_nested: a failed nested txn expires ORM state.
        attempts = job.attempts
        version_id = version.id
        storage_key = version.storage_key
        mime_type = version.mime_type
        doc_path = document.path
        doc_id = document.id
        workspace_id = document.workspace_id
        try:
            async with self.session.begin_nested():
                store = self._store()
                content = await store.get(storage_key)
                job.status = "parsing"
                parsed = await self._parser().parse(content, mime_type=mime_type, filename=doc_path)
                version.extra_metadata = parsed.metadata
                version.parser_provider = self.settings.parser.provider
                version.parser_version = "1"
                job.status = "chunking"
                chunks = await self._chunker().chunk(
                    parsed, document_id=doc_id, document_version_id=version_id
                )
                version.chunker_strategy = self.settings.chunking.strategy
                version.chunker_version = "1"
                job.status = "embedding"
                embedder = self._embedder()
                result = await embedder.embed_documents([c.text for c in chunks]) if chunks else None
                profile = await self._profile(result.dimensions if result else (self.settings.embedding.dimensions or 0))
                job.status = "indexing"
                vectors = self._vectors()
                records = []
                for i, chunk in enumerate(chunks):
                    row = DocumentChunk(
                        tenant_id=self.ctx.tenant_id,
                        document_id=doc_id,
                        version_id=version_id,
                        chunk_index=chunk.chunk_index,
                        text=chunk.text,
                        page=chunk.page,
                        section=chunk.section,
                        token_count=chunk.token_count,
                    )
                    self.session.add(row)
                    await self.session.flush()
                    chunk.chunk_id = row.id
                    if result:
                        records.append(
                            VectorRecord(
                                chunk_id=row.id,
                                document_id=doc_id,
                                version_id=version_id,
                                workspace_id=workspace_id,
                                tenant_id=self.ctx.require_tenant(),
                                embedding=result.vectors[i],
                                payload={"embedding_profile_id": str(profile.id)},
                            )
                        )
                if records:
                    await vectors.upsert(records)
                version.status = "completed"
                job.status = "completed"
                await self._stamp_derived(version, "completed")
        except Exception as exc:
            await self.session.refresh(job)
            await self.session.refresh(version)
            job.status = "failed" if attempts < 3 else "dead_letter"
            job.error = str(exc)
            await self.session.execute(
                update(DocumentVersion).where(DocumentVersion.id == version_id).values(status="failed")
            )
            await self._stamp_derived(version, "failed")

    async def list_documents(self, *, limit: int = 100, offset: int = 0) -> list[dict]:
        from app.api.pagination import clip_limit, clip_offset

        if not self.ctx.has("document:read"):
            raise ForbiddenError("Missing permission document:read")
        allowed_ids = await authorized_document_ids(
            self.session, self.ctx, limit=clip_limit(limit), offset=clip_offset(offset)
        )
        if not allowed_ids:
            return []
        rows = (
            await self.session.scalars(
                select(Document)
                .where(Document.id.in_(allowed_ids), Document.tenant_id == self.ctx.tenant_id)
                .order_by(Document.created_at.desc(), Document.id)
            )
        ).all()
        out = []
        from app.application.connectors import document_is_live, source_feeds_index
        from app.core.untrusted import untrusted_text

        for d in rows:
            if not document_is_live(d):
                continue
            if d.source_id:
                source = await self.session.get(DataSource, d.source_id)
                if not source_feeds_index(source):
                    continue
            version = None
            if d.active_version_id:
                version = await self.session.get(DocumentVersion, d.active_version_id)
            out.append(
                {
                    "id": str(d.id),
                    "title": untrusted_text(d.title),
                    "path": untrusted_text(d.path),
                    "classification": d.classification,
                    "active_version_id": str(d.active_version_id) if d.active_version_id else None,
                    "workspace_id": str(d.workspace_id),
                    "owner_user_id": str(d.owner_user_id) if d.owner_user_id else None,
                    "acl": d.acl or {},
                    "status": version.status if version else "pending",
                    "version_number": version.version_number if version else None,
                    "size_bytes": version.size_bytes if version else None,
                    "mime_type": version.mime_type if version else None,
                    "storage_key": version.storage_key if version else None,
                    "storage_provider": self.settings.storage.provider,
                    "storage_root": self.settings.storage.bucket,
                }
            )
        return out

    async def reembed_active(self) -> dict:
        if not self.ctx.has("document:write") and not self.ctx.has("config:write"):
            raise ForbiddenError("Missing permission to reindex")
        from app.application.connectors import document_is_live

        docs = (
            await self.session.scalars(select(Document).where(Document.tenant_id == self.ctx.tenant_id))
        ).all()
        embedder = self._embedder()
        vectors = self._vectors()
        profile = None
        updated = 0
        failed = 0
        skipped = 0
        for doc in docs:
            if not _visible(doc.acl or {}, self.ctx) or not document_is_live(doc) or not doc.active_version_id:
                skipped += 1
                continue
            chunks = list(
                (
                    await self.session.scalars(
                        select(DocumentChunk)
                        .where(DocumentChunk.version_id == doc.active_version_id)
                        .order_by(DocumentChunk.chunk_index.asc())
                    )
                ).all()
            )
            if not chunks:
                skipped += 1
                continue
            try:
                result = await embedder.embed_documents([c.text for c in chunks])
            except Exception:
                failed += 1
                continue
            if profile is None:
                profile = await self._profile(result.dimensions)
            await self.session.execute(delete(ChunkEmbedding).where(ChunkEmbedding.chunk_id.in_([c.id for c in chunks])))
            records = [
                VectorRecord(
                    chunk_id=chunk.id,
                    document_id=doc.id,
                    version_id=doc.active_version_id,
                    workspace_id=doc.workspace_id,
                    tenant_id=self.ctx.require_tenant(),
                    embedding=result.vectors[i],
                    payload={"embedding_profile_id": str(profile.id)},
                )
                for i, chunk in enumerate(chunks)
            ]
            await vectors.upsert(records)
            updated += 1
        await self.session.flush()
        return {
            "documents_embedded": updated,
            "failed": failed,
            "skipped": skipped,
            "provider": self.settings.embedding.provider,
            "model": self.settings.embedding.model,
        }

    async def list_versions(self, document_id: UUID) -> list[dict]:
        doc = await self.session.get(Document, document_id)
        from app.application.connectors import document_is_live

        if (
            doc is None
            or doc.tenant_id != self.ctx.tenant_id
            or not _visible(doc.acl or {}, self.ctx)
            or not document_is_live(doc)
        ):
            raise NotFoundError("Document not found")
        versions = (
            await self.session.scalars(
                select(DocumentVersion)
                .where(DocumentVersion.document_id == document_id)
                .order_by(DocumentVersion.version_number.asc())
            )
        ).all()
        return [
            {
                "id": str(v.id),
                "version_number": v.version_number,
                "status": v.status,
                "content_hash": v.content_hash,
                "derived_from_version_id": str(v.derived_from_version_id) if v.derived_from_version_id else None,
                "created_at": v.created_at.isoformat() if v.created_at else None,
            }
            for v in versions
        ]

    async def _profile(self, dimensions: int) -> EmbeddingProfile:
        existing = await self.session.scalar(
            select(EmbeddingProfile).where(
                EmbeddingProfile.tenant_id == self.ctx.tenant_id,
                EmbeddingProfile.provider == self.settings.embedding.provider,
                EmbeddingProfile.model == self.settings.embedding.model,
                EmbeddingProfile.dimensions == dimensions,
                EmbeddingProfile.version == "1",
            )
        )
        if existing:
            return existing
        profile = EmbeddingProfile(
            tenant_id=self.ctx.tenant_id,
            provider=self.settings.embedding.provider,
            model=self.settings.embedding.model,
            dimensions=dimensions or 1,
            version="1",
        )
        self.session.add(profile)
        await self.session.flush()
        return profile

    async def update_document_acl(self, document_id: UUID, patch: dict) -> dict:
        if not self.ctx.has("document:read"):
            raise ForbiddenError("Missing permission document:read")
        document = await self.session.get(Document, document_id)
        if document is None or document.tenant_id != self.ctx.tenant_id:
            raise NotFoundError("Document not found")
        if not can_share_document(document, self.ctx):
            # 403 only when the caller can already read the document. Otherwise
            # 404 so a guess at another user's private id does not confirm it exists.
            if can_read_document(document.acl or {}, self.ctx):
                raise ForbiddenError("Only the document owner or a tenant admin can change visibility")
            raise NotFoundError("Document not found")
        owner_id = document.owner_user_id or self.ctx.user_id
        if owner_id is None:
            raise ValidationFailedError("Document owner is required")
        allowed_users = await resolve_share_user_ids(
            self.session,
            self.ctx,
            user_ids=patch.get("allowed_users"),
            emails=patch.get("emails"),
        )
        denied_users = await resolve_share_user_ids(
            self.session,
            self.ctx,
            user_ids=patch.get("denied_users"),
            emails=patch.get("denied_emails"),
        )
        allowed_roles = patch.get("allowed_roles")
        if allowed_roles is not None:
            from app.application.authz import normalize_allowed_roles

            allowed_roles = normalize_allowed_roles(allowed_roles)
        fields = {
            "allowed_users": allowed_users if (patch.get("allowed_users") is not None or patch.get("emails") is not None) else None,
            "denied_users": denied_users if (patch.get("denied_users") is not None or patch.get("denied_emails") is not None) else None,
            "allowed_roles": allowed_roles,
            "allowed_groups": patch.get("allowed_groups"),
            "denied_roles": patch.get("denied_roles"),
            "denied_groups": patch.get("denied_groups"),
            "visibility": patch.get("visibility"),
        }
        acl_patch = {k: v for k, v in fields.items() if v is not None}
        document.acl = apply_acl_patch(owner_id, document.acl or {}, acl_patch)
        document.owner_user_id = owner_id
        await self.session.flush()
        await write_audit(
            self.session,
            tenant_id=self.ctx.tenant_id,
            actor_user_id=self.ctx.user_id,
            action="document.share",
            resource_type="document",
            resource_id=document.id,
            request_id=self.ctx.request_id,
        )
        await persist_authz_bump(self.session, self.ctx.require_tenant())
        return {"id": str(document.id), "acl": document.acl}


def _visible(acl: dict, ctx: RequestContext) -> bool:
    return can_read_document(acl, ctx)
