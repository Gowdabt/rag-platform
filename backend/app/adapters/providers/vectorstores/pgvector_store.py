from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.db.models import ChunkEmbedding, DocumentChunk
from app.application.authz import document_acl_params, document_acl_sql
from app.application.content_address import LOGICAL_CHUNK_FROM
from app.config.models import VectorStoreConfig
from app.core.context import RequestContext
from app.core.errors import ValidationFailedError
from app.domain.ports.vectorstore import VectorStore
from app.domain.registry import register
from app.domain.types import VectorFilter, VectorHit, VectorRecord


@register("vector_store", "pgvector")
class PgVectorStore(VectorStore):
    def __init__(self, config: VectorStoreConfig, ctx: RequestContext, session: AsyncSession | None = None):
        super().__init__(config, ctx)
        self.session = session

    def _session(self) -> AsyncSession:
        if self.session is None:
            raise ValidationFailedError("pgvector store requires a database session")
        return self.session

    async def create_collection(self, *, dimensions: int) -> None:
        return None

    async def upsert(self, records: list[VectorRecord]) -> None:
        session = self._session()
        for rec in records:
            if rec.tenant_id != self.ctx.tenant_id:
                raise ValidationFailedError("tenant_id mismatch on vector upsert")
            existing = await session.scalar(
                select(ChunkEmbedding).where(ChunkEmbedding.chunk_id == rec.chunk_id)
            )
            profile_id = rec.payload.get("embedding_profile_id")
            if existing:
                existing.embedding = rec.embedding
            else:
                session.add(
                    ChunkEmbedding(
                        tenant_id=rec.tenant_id,
                        chunk_id=rec.chunk_id,
                        embedding_profile_id=UUID(str(profile_id)) if profile_id else rec.chunk_id,
                        embedding=rec.embedding,
                    )
                )
        await session.flush()

    async def search(
        self, embedding: list[float], *, top_k: int, filters: VectorFilter
    ) -> list[VectorHit]:
        if filters.tenant_id is None:
            raise ValidationFailedError("tenant_id filter is required")
        session = self._session()
        vec = "[" + ",".join(str(x) for x in embedding) + "]"
        sql = f"""
            SELECT c.id, d.id, v.id,
                   1 - (e.embedding <=> CAST(:vec AS vector)) AS score
            {LOGICAL_CHUNK_FROM}
            JOIN chunk_embeddings e ON e.chunk_id = c.id
            JOIN embedding_profiles p ON p.id = e.embedding_profile_id
            WHERE e.tenant_id = :tenant
              AND d.tenant_id = :tenant
        """
        params: dict = {"vec": vec, "tenant": str(filters.tenant_id), "k": top_k}
        if filters.embedding_provider:
            sql += " AND p.provider = :emb_provider"
            params["emb_provider"] = filters.embedding_provider
        if filters.embedding_model:
            sql += " AND p.model = :emb_model"
            params["emb_model"] = filters.embedding_model
        if filters.workspace_id:
            sql += " AND d.workspace_id = :workspace"
            params["workspace"] = str(filters.workspace_id)
        if filters.version_id:
            sql += " AND v.id = :version"
            params["version"] = str(filters.version_id)
        elif filters.document_ids:
            sql += " AND d.id = ANY(:docs)"
            params["docs"] = [str(i) for i in filters.document_ids]
        sql += document_acl_sql("d")
        params.update(document_acl_params(filters))
        sql += " ORDER BY e.embedding <=> CAST(:vec AS vector) LIMIT :k"
        rows = (await session.execute(text(sql), params)).all()
        return [
            VectorHit(
                chunk_id=row[0],
                document_id=row[1],
                version_id=row[2],
                score=float(row[3] or 0),
                payload={},
            )
            for row in rows
        ]

    async def delete(self, chunk_ids: list[UUID], *, filters: VectorFilter) -> None:
        session = self._session()
        await session.execute(
            delete(ChunkEmbedding).where(
                ChunkEmbedding.tenant_id == filters.tenant_id,
                ChunkEmbedding.chunk_id.in_(chunk_ids),
            )
        )

    async def delete_document(self, document_id: UUID, *, filters: VectorFilter) -> None:
        session = self._session()
        chunk_ids = (
            await session.scalars(
                select(DocumentChunk.id).where(
                    DocumentChunk.document_id == document_id,
                    DocumentChunk.tenant_id == filters.tenant_id,
                )
            )
        ).all()
        if chunk_ids:
            await self.delete(list(chunk_ids), filters=filters)

    async def health_check(self) -> bool:
        session = self._session()
        await session.execute(text("SELECT 1"))
        return True
