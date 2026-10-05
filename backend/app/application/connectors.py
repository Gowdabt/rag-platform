from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.adapters.db.models import (
    ConfigOverlay,
    ConnectorCredential,
    DataSource,
    Document,
    Folder,
    IngestionJob,
    OAuthState,
    SourceSubscription,
    SyncRun,
)
from app.adapters.providers.connectors.local_fs import list_host_folders
from app.adapters.providers.connectors.oauth import (
    PROVIDER_GROUP,
    assert_oauth_redirect_uri,
    encrypt_secret,
    oauth_clients_status,
    oauth_is_configured,
)
from app.application.audit import write_audit
from app.application.authz import (
    apply_acl_patch,
    assert_workspace_access,
    can_manage_source,
    inherit_acl,
    owner_acl,
    resolve_share_user_ids,
)
from app.application.authz_epoch import persist_authz_bump
from app.application.factory import ProviderFactory
from app.application.ingestion import IngestionService
from app.config.merge import deep_merge
from app.config.models import PlatformSettings
from app.core.context import RequestContext
from app.core.crypto import LocalTokenCipher
from app.core.errors import (
    ConnectorAuthExpiredError,
    ForbiddenError,
    NotFoundError,
    ValidationFailedError,
)
from app.domain.registry import registry
from app.domain.types import ConnectorFile


def _include_mocks() -> bool:
    return os.environ.get("RAG_CONNECTOR_MOCKS", "").lower() in {"1", "true", "yes"}


def document_is_live(doc: Document) -> bool:
    return (doc.external_status or "active") == "active"


def source_feeds_index(source: DataSource | None) -> bool:
    if source is None:
        return False
    if source.status == "disconnected":
        return False
    if str(source.connector_type).startswith("mock_") and not _include_mocks():
        return False
    return True


def _reject_disabled_mock(connector_type: str) -> None:
    if str(connector_type).startswith("mock_") and not _include_mocks():
        raise ValidationFailedError("Mock connectors are disabled in this environment.")


def list_connector_catalog(clients: dict | None = None) -> list[dict]:
    items = []
    include_mocks = _include_mocks()
    for kind, name in registry.registered("connector"):
        factory = registry.get(kind, name)
        definition = getattr(factory, "definition", None)
        if definition is None:
            continue
        if definition.mock and not include_mocks:
            continue
        payload = definition.model_dump()
        if definition.authentication == "oauth2":
            payload["configured"] = oauth_is_configured(definition.id, clients)
            payload["oauth_group"] = PROVIDER_GROUP.get(definition.id)
        elif definition.id == "s3":
            try:
                import boto3  # noqa: F401

                payload["configured"] = True
            except ImportError:
                payload["configured"] = False
        else:
            payload["configured"] = True
        items.append(payload)
    return sorted(items, key=lambda d: d["name"])


def next_sync_at(schedule: str, *, now: datetime | None = None) -> datetime | None:
    now = now or datetime.now(UTC)
    mapping = {
        "every_30_minutes": timedelta(minutes=30),
        "hourly": timedelta(hours=1),
        "daily": timedelta(days=1),
    }
    delta = mapping.get(schedule)
    return now + delta if delta else None


class ConnectorService:
    def __init__(self, session: AsyncSession, settings: PlatformSettings, ctx: RequestContext):
        self.session = session
        self.settings = settings
        self.ctx = ctx
        self.factory = ProviderFactory(settings, ctx)
        self.cipher = LocalTokenCipher()
        self._oauth_clients_cache: dict | None = None
        self._overlay_payload: dict | None = None

    async def tenant_overlay(self) -> dict:
        if self._overlay_payload is not None:
            return self._overlay_payload
        overlay = await self.session.scalar(
            select(ConfigOverlay).where(
                ConfigOverlay.tenant_id == self.ctx.tenant_id,
                ConfigOverlay.scope_type == "tenant",
            )
        )
        self._overlay_payload = dict(overlay.payload or {}) if overlay else {}
        return self._overlay_payload

    def _settings_oauth_clients(self) -> dict:
        oauth = self.settings.oauth
        return {
            "google": oauth.google.model_dump(),
            "microsoft": oauth.microsoft.model_dump(),
            "dropbox": oauth.dropbox.model_dump(),
        }

    async def oauth_clients(self) -> dict:
        if self._oauth_clients_cache is not None:
            return self._oauth_clients_cache
        clients = self._settings_oauth_clients()
        payload = await self.tenant_overlay()
        if isinstance(payload.get("oauth"), dict):
            clients = deep_merge(clients, payload["oauth"])
        self._oauth_clients_cache = clients
        return clients

    async def oauth_status(self) -> dict:
        clients = await self.oauth_clients()
        return {
            "clients": oauth_clients_status(clients),
            "redirect_uris": [
                "http://127.0.0.1:5173/sources",
                "http://localhost:5173/sources",
                "http://127.0.0.1:8000/sources",
                "http://localhost:8000/sources",
            ],
        }

    async def save_oauth_clients(self, patch: dict) -> dict:
        if not (self.ctx.has("config:write") or self.ctx.has("source:admin")):
            raise ForbiddenError("Missing permission to save OAuth clients")
        cleaned: dict[str, dict[str, str]] = {}
        for group in ("google", "microsoft", "dropbox"):
            raw = patch.get(group)
            if not isinstance(raw, dict):
                continue
            client_id = str(raw.get("client_id") or "").strip()
            client_secret = str(raw.get("client_secret") or "").strip()
            if not client_id or not client_secret:
                continue
            cleaned[group] = {"client_id": client_id, "client_secret": encrypt_secret(client_secret)}
        if not cleaned:
            raise ValidationFailedError("Provide a client ID and secret for at least one provider.")
        overlay = await self.session.scalar(
            select(ConfigOverlay).where(
                ConfigOverlay.tenant_id == self.ctx.tenant_id,
                ConfigOverlay.scope_type == "tenant",
            )
        )
        if overlay is None:
            overlay = ConfigOverlay(
                tenant_id=self.ctx.require_tenant(),
                scope_type="tenant",
                scope_id=self.ctx.require_tenant(),
                payload={"oauth": cleaned},
                version=1,
            )
            self.session.add(overlay)
        else:
            payload = dict(overlay.payload or {})
            payload["oauth"] = deep_merge(payload.get("oauth") or {}, cleaned)
            overlay.payload = payload
            overlay.version += 1
            flag_modified(overlay, "payload")
        await self.session.flush()
        self._oauth_clients_cache = None
        self._overlay_payload = None
        return await self.oauth_status()

    def _require_manage(self) -> None:
        if not self.ctx.has("source:manage") and not self.ctx.has("source:admin"):
            raise ForbiddenError("Missing permission source:manage")

    def _require_owned_source(self, source: DataSource) -> None:
        if not can_manage_source(source, self.ctx):
            raise NotFoundError("Connector not found")

    async def _owned_source(self, source_id: UUID) -> DataSource:
        source = await self._source(source_id)
        self._require_owned_source(source)
        return source

    def _local_fs_extra_roots(self) -> list[str]:
        roots = list(self.settings.connectors.fs_roots or [])
        extra = (self._overlay_payload or {}).get("connectors") or {}
        if isinstance(extra, dict):
            roots.extend(str(item) for item in (extra.get("fs_roots") or []) if item)
        return roots

    def _adapter(self, connector_type: str, config: dict | None = None):
        cfg = dict(config or {})
        if "_oauth_clients" not in cfg and self._oauth_clients_cache is not None:
            cfg["_oauth_clients"] = self._oauth_clients_cache
        if str(connector_type) == "local_fs":
            cfg["_fs_roots"] = self._local_fs_extra_roots()
            cfg["_fs_isolation"] = self.settings.connectors.fs_isolation
            if self.ctx.tenant_id:
                cfg["_tenant_id"] = str(self.ctx.tenant_id)
            if self.ctx.user_id:
                cfg["_user_id"] = str(self.ctx.user_id)
        return self.factory.create("connector", connector_type, config=cfg, ctx=self.ctx)

    async def browse_local_host(self, path: str | None) -> dict:
        self._require_manage()
        await self.tenant_overlay()
        return list_host_folders(
            path,
            extra=self._local_fs_extra_roots(),
            isolation=self.settings.connectors.fs_isolation,
            tenant_id=self.ctx.tenant_id,
            user_id=self.ctx.user_id,
        )

    async def _adapter_for_source(self, source: DataSource, extra: dict | None = None):
        self._require_owned_source(source)
        await self.tenant_overlay()
        config = dict(source.connector_config or {})
        config.pop("_oauth_clients", None)
        if extra:
            extra = dict(extra)
            extra.pop("_oauth_clients", None)
            config.update(extra)
        config["_oauth_clients"] = await self.oauth_clients()
        cred = await self.session.scalar(select(ConnectorCredential).where(ConnectorCredential.source_id == source.id))
        if cred:
            if cred.expires_at and cred.expires_at < datetime.now(UTC) + timedelta(minutes=2) and cred.encrypted_refresh_token:
                adapter = self._adapter(source.connector_type, config)
                tokens = await adapter.refresh_authentication(self.cipher.decrypt(cred.encrypted_refresh_token))
                cred.encrypted_access_token = self.cipher.encrypt(tokens.access_token)
                if tokens.refresh_token:
                    cred.encrypted_refresh_token = self.cipher.encrypt(tokens.refresh_token)
                cred.expires_at = datetime.now(UTC) + timedelta(seconds=tokens.expires_in)
                await self.session.flush()
            raw = self.cipher.decrypt(cred.encrypted_access_token)
            try:
                payload = json.loads(raw)
                if isinstance(payload, dict):
                    config.update(payload)
                else:
                    config["access_token"] = raw
            except json.JSONDecodeError:
                config["access_token"] = raw
            if cred.encrypted_refresh_token:
                config["refresh_token"] = self.cipher.decrypt(cred.encrypted_refresh_token)
        return self._adapter(source.connector_type, config)

    async def _source(self, source_id: UUID) -> DataSource:
        source = await self.session.get(DataSource, source_id)
        if source is None or source.tenant_id != self.ctx.tenant_id:
            raise NotFoundError("Connector not found")
        return source

    async def list_sources(self, *, limit: int = 100, offset: int = 0) -> list[dict]:
        from app.api.pagination import clip_limit, clip_offset
        if not self.ctx.has("document:read") and not self.ctx.has("source:manage"):
            raise ForbiddenError("Missing permission to list sources")
        stmt = select(DataSource).where(
            DataSource.tenant_id == self.ctx.tenant_id,
            DataSource.connector_type != "upload",
            DataSource.status != "disconnected",
        )
        if not self.ctx.has("source:admin"):
            stmt = stmt.where(DataSource.owner_user_id == self.ctx.user_id)
        include_mocks = _include_mocks()
        if not include_mocks:
            stmt = stmt.where(~DataSource.connector_type.like("mock_%"))
        stmt = stmt.order_by(DataSource.created_at.desc(), DataSource.id).offset(clip_offset(offset)).limit(clip_limit(limit))
        rows = (await self.session.scalars(stmt)).all()
        out = []
        for source in rows:
            subs = (
                await self.session.scalars(
                    select(SourceSubscription).where(SourceSubscription.source_id == source.id)
                )
            ).all()
            cred = await self.session.scalar(
                select(ConnectorCredential).where(ConnectorCredential.source_id == source.id)
            )
            doc_count = 0
            for sub in subs:
                doc_count += int(
                    await self.session.scalar(
                        select(func.count()).select_from(Document).where(
                            Document.subscription_id == sub.id,
                            Document.external_status == "active",
                        )
                    )
                    or 0
                )
            out.append(
                {
                    "id": str(source.id),
                    "name": source.name,
                    "connector_type": source.connector_type,
                    "status": source.status,
                    "account_label": cred.account_label if cred else None,
                    "last_synced_at": source.last_synced_at.isoformat() if source.last_synced_at else None,
                    "last_error": source.last_error,
                    "document_count": doc_count,
                    "subscriptions": [self._sub_payload(s) for s in subs],
                }
            )
        return out

    def _sub_payload(self, sub: SourceSubscription) -> dict:
        return {
            "id": str(sub.id),
            "source_id": str(sub.source_id),
            "external_location_id": sub.external_location_id,
            "external_location_name": sub.external_location_name,
            "include_subfolders": sub.include_subfolders,
            "file_filters": sub.file_filters,
            "sync_mode": sub.sync_mode,
            "schedule": sub.schedule,
            "status": sub.status,
            "last_sync_at": sub.last_sync_at.isoformat() if sub.last_sync_at else None,
            "next_sync_at": sub.next_sync_at.isoformat() if sub.next_sync_at else None,
            "last_error": sub.last_error,
            "acl": sub.acl or {},
        }

    async def start_oauth(
        self,
        *,
        connector_type: str,
        workspace_id: UUID | None,
        redirect_uri: str,
        source_id: UUID | None = None,
    ) -> dict:
        self._require_manage()
        _reject_disabled_mock(connector_type)
        redirect_uri = assert_oauth_redirect_uri(redirect_uri)
        preferred = None
        if source_id is not None:
            preferred = await self._owned_source(source_id)
            if preferred.connector_type != connector_type:
                raise ValidationFailedError("Source does not match this connector")
        adapter = self._adapter(connector_type, {"_oauth_clients": await self.oauth_clients()})
        resolved_workspace = workspace_id or (preferred.workspace_id if preferred else self.ctx.workspace_id)
        if resolved_workspace is None:
            raise ValidationFailedError("workspace_id is required")
        await assert_workspace_access(self.session, self.ctx, resolved_workspace)
        state = uuid4().hex
        expires = datetime.now(UTC) + timedelta(minutes=15)
        row = OAuthState(
            tenant_id=self.ctx.require_tenant(),
            user_id=self.ctx.user_id,
            workspace_id=resolved_workspace,
            connector_type=connector_type,
            state=state,
            redirect_uri=redirect_uri,
            source_id=preferred.id if preferred else None,
            expires_at=expires,
        )
        self.session.add(row)
        await self.session.flush()
        url = await adapter.authorization_url(redirect_uri=redirect_uri, state=state)
        return {"authorization_url": url, "state": state, "authentication": adapter.definition.authentication}

    async def complete_oauth(self, *, code: str, state: str) -> dict:
        self._require_manage()
        row = await self.session.scalar(select(OAuthState).where(OAuthState.state == state))
        if row is None or row.tenant_id != self.ctx.tenant_id or row.user_id != self.ctx.user_id:
            raise NotFoundError("OAuth state not found")
        if row.expires_at < datetime.now(UTC):
            raise ConnectorAuthExpiredError("OAuth state expired")
        adapter = self._adapter(row.connector_type, {"_oauth_clients": await self.oauth_clients()})
        tokens = await adapter.authenticate({"code": code, "redirect_uri": row.redirect_uri or ""})
        workspace_id = row.workspace_id or self.ctx.workspace_id
        if workspace_id is None:
            raise ValidationFailedError("workspace_id is required")
        await assert_workspace_access(self.session, self.ctx, workspace_id)
        source, reused = await self._reuse_or_create_oauth_source(
            connector_type=row.connector_type,
            workspace_id=workspace_id,
            preferred_id=row.source_id,
            account_label=tokens.account_label,
            adapter_name=adapter.definition.name,
            mock=adapter.definition.mock,
        )
        await self._save_oauth_tokens(source, tokens)
        source.status = "connected"
        source.last_error = None
        await self._collapse_duplicate_oauth_sources(source, tokens.account_label)
        await self.session.delete(row)
        await self.session.flush()
        sub_count = int(
            await self.session.scalar(
                select(func.count()).select_from(SourceSubscription).where(
                    SourceSubscription.source_id == source.id,
                    SourceSubscription.status != "disconnected",
                )
            )
            or 0
        )
        return {
            "id": str(source.id),
            "status": source.status,
            "account_label": tokens.account_label,
            "reused": reused,
            "has_subscriptions": sub_count > 0,
        }

    async def _reuse_or_create_oauth_source(
        self,
        *,
        connector_type: str,
        workspace_id: UUID,
        preferred_id: UUID | None,
        account_label: str | None,
        adapter_name: str,
        mock: bool,
    ) -> tuple[DataSource, bool]:
        tenant = self.ctx.require_tenant()
        if preferred_id:
            preferred = await self.session.get(DataSource, preferred_id)
            if (
                preferred
                and preferred.tenant_id == tenant
                and preferred.connector_type == connector_type
                and can_manage_source(preferred, self.ctx)
            ):
                if preferred.owner_user_id is None:
                    preferred.owner_user_id = self.ctx.user_id
                return preferred, True
        sources = list(
            (
                await self.session.scalars(
                    select(DataSource).where(
                        DataSource.tenant_id == tenant,
                        DataSource.workspace_id == workspace_id,
                        DataSource.connector_type == connector_type,
                        DataSource.owner_user_id == self.ctx.user_id,
                    )
                )
            ).all()
        )
        if not sources:
            source = DataSource(
                tenant_id=tenant,
                workspace_id=workspace_id,
                owner_user_id=self.ctx.user_id,
                name=adapter_name,
                connector_type=connector_type,
                status="connected",
                connector_config={"mock": mock},
            )
            self.session.add(source)
            await self.session.flush()
            return source, False
        creds = {
            c.source_id: c
            for c in (
                await self.session.scalars(
                    select(ConnectorCredential).where(
                        ConnectorCredential.source_id.in_([s.id for s in sources])
                    )
                )
            ).all()
        }
        labeled = [
            s
            for s in sources
            if account_label and (creds.get(s.id) and creds[s.id].account_label == account_label)
        ]
        if not labeled:
            source = DataSource(
                tenant_id=tenant,
                workspace_id=workspace_id,
                owner_user_id=self.ctx.user_id,
                name=adapter_name,
                connector_type=connector_type,
                status="connected",
                connector_config={"mock": mock},
            )
            self.session.add(source)
            await self.session.flush()
            return source, False
        pool = labeled
        scored = []
        for source in pool:
            sub_n = int(
                await self.session.scalar(
                    select(func.count()).select_from(SourceSubscription).where(
                        SourceSubscription.source_id == source.id,
                        SourceSubscription.status != "disconnected",
                    )
                )
                or 0
            )
            rank = (
                2 if source.status == "connected" else 1 if source.status == "auth_expired" else 0,
                sub_n,
                source.updated_at or source.created_at,
            )
            scored.append((rank, source))
        scored.sort(key=lambda item: item[0], reverse=True)
        return scored[0][1], True

    async def _save_oauth_tokens(self, source: DataSource, tokens) -> None:
        cred = await self.session.scalar(
            select(ConnectorCredential).where(ConnectorCredential.source_id == source.id)
        )
        if cred is None:
            cred = ConnectorCredential(
                tenant_id=self.ctx.require_tenant(),
                source_id=source.id,
            )
            self.session.add(cred)
        cred.encrypted_access_token = self.cipher.encrypt(tokens.access_token)
        cred.encrypted_refresh_token = (
            self.cipher.encrypt(tokens.refresh_token) if tokens.refresh_token else None
        )
        cred.expires_at = datetime.now(UTC) + timedelta(seconds=tokens.expires_in)
        cred.scopes = tokens.scopes
        cred.account_label = tokens.account_label

    async def _collapse_duplicate_oauth_sources(self, keeper: DataSource, account_label: str | None) -> None:
        if not account_label:
            return
        tenant = self.ctx.require_tenant()
        others = list(
            (
                await self.session.scalars(
                    select(DataSource).where(
                        DataSource.tenant_id == tenant,
                        DataSource.workspace_id == keeper.workspace_id,
                        DataSource.connector_type == keeper.connector_type,
                        DataSource.owner_user_id == keeper.owner_user_id,
                        DataSource.id != keeper.id,
                    )
                )
            ).all()
        )
        for other in others:
            cred = await self.session.scalar(
                select(ConnectorCredential).where(ConnectorCredential.source_id == other.id)
            )
            if cred is None or cred.account_label != account_label:
                continue
            keeper_locs = {
                s.external_location_id
                for s in (
                    await self.session.scalars(
                        select(SourceSubscription).where(SourceSubscription.source_id == keeper.id)
                    )
                ).all()
            }
            for sub in (
                await self.session.scalars(
                    select(SourceSubscription).where(SourceSubscription.source_id == other.id)
                )
            ).all():
                if sub.external_location_id in keeper_locs:
                    continue
                sub.source_id = keeper.id
                await self.session.flush()
            doc_count = int(
                await self.session.scalar(
                    select(func.count()).select_from(Document).where(Document.source_id == other.id)
                )
                or 0
            )
            if doc_count == 0:
                await self.disconnect(other.id, revoke=False)


    async def create_unauthenticated(
        self,
        *,
        connector_type: str,
        workspace_id: UUID | None,
        name: str | None,
        connector_config: dict | None = None,
    ) -> dict:
        self._require_manage()
        _reject_disabled_mock(connector_type)
        config = dict(connector_config or {})
        secrets = {key: config.pop(key) for key in ("access_key", "secret_key") if config.get(key)}
        await self.tenant_overlay()
        adapter = self._adapter(connector_type, config)
        if adapter.definition.authentication not in {"none", "api_key"}:
            raise ValidationFailedError("This connector requires OAuth")
        workspace_id = workspace_id or self.ctx.workspace_id
        if workspace_id is None:
            raise ValidationFailedError("workspace_id is required")
        await assert_workspace_access(self.session, self.ctx, workspace_id)
        await adapter.connect()
        source = DataSource(
            tenant_id=self.ctx.require_tenant(),
            workspace_id=workspace_id,
            owner_user_id=self.ctx.user_id,
            name=name or adapter.definition.name,
            connector_type=connector_type,
            status="connected",
            connector_config={**config, "mock": adapter.definition.mock},
        )
        self.session.add(source)
        await self.session.flush()
        if secrets:
            self.session.add(
                ConnectorCredential(
                    tenant_id=self.ctx.require_tenant(),
                    source_id=source.id,
                    encrypted_access_token=self.cipher.encrypt(json.dumps(secrets)),
                    account_label=config.get("bucket") or config.get("root_path"),
                    expires_at=datetime.now(UTC) + timedelta(days=3650),
                )
            )
            await self.session.flush()
        await write_audit(
            self.session,
            tenant_id=self.ctx.tenant_id,
            actor_user_id=self.ctx.user_id,
            action="connector.create",
            resource_type="connector",
            resource_id=source.id,
            metadata={"connector_type": connector_type},
            request_id=self.ctx.request_id,
        )
        return {"id": str(source.id), "status": source.status}

    async def disconnect(self, source_id: UUID, *, revoke: bool = True) -> dict:
        source = await self._owned_source(source_id)
        if revoke:
            try:
                adapter = await self._adapter_for_source(source)
                await adapter.disconnect()
            except Exception:
                pass
        tenant = self.ctx.require_tenant()
        await self.session.execute(
            update(Document)
            .where(Document.tenant_id == tenant, Document.source_id == source.id)
            .values(external_status="deleted_externally")
        )
        await self.session.execute(
            delete(ConnectorCredential).where(
                ConnectorCredential.tenant_id == tenant,
                ConnectorCredential.source_id == source.id,
            )
        )
        await self.session.execute(
            update(IngestionJob)
            .where(IngestionJob.tenant_id == tenant, IngestionJob.source_id == source.id)
            .values(source_id=None)
        )
        await self.session.execute(
            update(SourceSubscription)
            .where(SourceSubscription.tenant_id == tenant, SourceSubscription.source_id == source.id)
            .values(status="disconnected", next_sync_at=None)
        )
        doc_count = int(
            await self.session.scalar(
                select(func.count()).select_from(Document).where(
                    Document.tenant_id == tenant,
                    Document.source_id == source.id,
                )
            )
            or 0
        )
        if doc_count == 0:
            await self.session.execute(
                delete(SourceSubscription).where(
                    SourceSubscription.tenant_id == tenant,
                    SourceSubscription.source_id == source.id,
                )
            )
            await self.session.delete(source)
        else:
            source.status = "disconnected"
            source.last_error = None
        await self.session.flush()
        await write_audit(
            self.session,
            tenant_id=tenant,
            actor_user_id=self.ctx.user_id,
            action="connector.disconnect",
            resource_type="connector",
            resource_id=source_id,
            request_id=self.ctx.request_id,
        )
        await persist_authz_bump(self.session, tenant)
        return {"id": str(source_id), "status": "disconnected"}

    async def resolve_location(self, source_id: UUID, raw: str) -> dict:
        source = await self._owned_source(source_id)
        adapter = await self._adapter_for_source(source)
        resolve = getattr(adapter, "resolve_location", None)
        if resolve is None:
            raise ValidationFailedError("This source does not support opening a folder from a URL")
        loc = await resolve(raw)
        payload = loc.model_dump()
        payload["kind"] = "folder"
        return payload

    async def locations(self, source_id: UUID, parent_id: str | None) -> list[dict]:
        source = await self._owned_source(source_id)
        adapter = await self._adapter_for_source(source)
        items = await adapter.list_locations(parent_id)
        return [i.model_dump() for i in items]

    async def browse(self, source_id: UUID, location_id: str) -> list[dict]:
        source = await self._owned_source(source_id)
        adapter = await self._adapter_for_source(source)
        items = await adapter.browse(location_id)
        out = []
        for item in items:
            payload = item.model_dump()
            payload["kind"] = "file" if isinstance(item, ConnectorFile) else "folder"
            out.append(payload)
        return out

    async def health(self, source_id: UUID) -> dict:
        source = await self._owned_source(source_id)
        adapter = await self._adapter_for_source(source)
        return await adapter.health_check()

    async def subscribe(
        self,
        source_id: UUID,
        *,
        location_id: str,
        location_name: str,
        include_subfolders: bool = True,
        file_filters: list[str] | None = None,
        schedule: str = "manual",
    ) -> dict:
        source = await self._owned_source(source_id)
        existing = await self.session.scalar(
            select(SourceSubscription).where(
                SourceSubscription.source_id == source.id,
                SourceSubscription.external_location_id == location_id,
            )
        )
        if existing:
            return self._sub_payload(existing)
        folder = Folder(
            tenant_id=self.ctx.require_tenant(),
            workspace_id=source.workspace_id,
            name=location_name,
            owner_user_id=self.ctx.user_id,
        )
        self.session.add(folder)
        await self.session.flush()
        sub = SourceSubscription(
            tenant_id=self.ctx.require_tenant(),
            workspace_id=source.workspace_id,
            source_id=source.id,
            external_location_id=location_id,
            external_location_name=location_name,
            include_subfolders=include_subfolders,
            file_filters=file_filters or ["pdf", "md", "markdown", "txt", "html", "htm", "csv", "json", "docx", "xlsx", "pptx"],
            schedule=schedule,
            status="active",
            acl=owner_acl(self.ctx.user_id) if self.ctx.user_id else {},
            next_sync_at=next_sync_at(schedule),
            folder_id=folder.id,
        )
        self.session.add(sub)
        await self.session.flush()
        return self._sub_payload(sub)

    async def list_subscriptions(self, *, limit: int = 100, offset: int = 0) -> list[dict]:
        from app.api.pagination import clip_limit, clip_offset

        if not self.ctx.has("document:read") and not self.ctx.has("source:manage") and not self.ctx.has("source:admin"):
            raise ForbiddenError("Missing permission")
        stmt = (
            select(SourceSubscription)
            .join(DataSource, DataSource.id == SourceSubscription.source_id)
            .where(SourceSubscription.tenant_id == self.ctx.tenant_id)
        )
        if not self.ctx.has("source:admin"):
            stmt = stmt.where(DataSource.owner_user_id == self.ctx.user_id)
        rows = (
            await self.session.scalars(
                stmt.order_by(SourceSubscription.created_at.desc(), SourceSubscription.id)
                .offset(clip_offset(offset))
                .limit(clip_limit(limit))
            )
        ).all()
        return [self._sub_payload(s) for s in rows]

    async def _owned_subscription(self, subscription_id: UUID) -> tuple[SourceSubscription, DataSource]:
        sub = await self.session.get(SourceSubscription, subscription_id)
        if sub is None or sub.tenant_id != self.ctx.tenant_id:
            raise NotFoundError("Subscription not found")
        source = await self._owned_source(sub.source_id)
        return sub, source

    async def patch_subscription(self, subscription_id: UUID, **fields) -> dict:
        sub, source = await self._owned_subscription(subscription_id)
        for key in ("status", "schedule", "include_subfolders", "file_filters"):
            if key in fields and fields[key] is not None:
                setattr(sub, key, fields[key])
        if fields.get("schedule"):
            sub.next_sync_at = next_sync_at(sub.schedule)
        acl_keys = (
            "allowed_users",
            "emails",
            "allowed_roles",
            "allowed_groups",
            "denied_users",
            "denied_emails",
            "denied_roles",
            "denied_groups",
            "visibility",
        )
        if any(key in fields and fields[key] is not None for key in acl_keys):
            await self._set_subscription_acl(sub, source, fields)
        await self.session.flush()
        return self._sub_payload(sub)

    async def _set_subscription_acl(self, sub: SourceSubscription, source: DataSource, patch: dict) -> None:
        owner_id = source.owner_user_id or self.ctx.user_id
        if owner_id is None:
            raise ValidationFailedError("Source owner is required")
        acl_patch: dict = {}
        if patch.get("allowed_users") is not None or patch.get("emails") is not None:
            acl_patch["allowed_users"] = await resolve_share_user_ids(
                self.session, self.ctx, user_ids=patch.get("allowed_users"), emails=patch.get("emails")
            )
        if patch.get("denied_users") is not None or patch.get("denied_emails") is not None:
            acl_patch["denied_users"] = await resolve_share_user_ids(
                self.session, self.ctx, user_ids=patch.get("denied_users"), emails=patch.get("denied_emails")
            )
        for key in ("allowed_roles", "allowed_groups", "denied_roles", "denied_groups", "visibility"):
            if patch.get(key) is not None:
                acl_patch[key] = patch[key]
        sub.acl = apply_acl_patch(owner_id, sub.acl or {}, acl_patch)
        flag_modified(sub, "acl")
        await self._propagate_subscription_acl(sub, source)
        await write_audit(
            self.session,
            tenant_id=self.ctx.tenant_id,
            actor_user_id=self.ctx.user_id,
            action="connector.share",
            resource_type="subscription",
            resource_id=sub.id,
            request_id=self.ctx.request_id,
        )
        await persist_authz_bump(self.session, self.ctx.require_tenant())

    async def _propagate_subscription_acl(self, sub: SourceSubscription, source: DataSource) -> None:
        docs = (
            await self.session.scalars(
                select(Document).where(
                    Document.subscription_id == sub.id,
                    Document.external_status == "active",
                )
            )
        ).all()
        for doc in docs:
            owner_id = doc.owner_user_id or source.owner_user_id
            if owner_id is None:
                continue
            doc.acl = inherit_acl(doc.acl, owner_id, sub.acl)
            doc.owner_user_id = owner_id
            flag_modified(doc, "acl")

    async def delete_subscription(self, subscription_id: UUID) -> None:
        sub, _source = await self._owned_subscription(subscription_id)
        sub.status = "disconnected"
        await self.session.flush()

    async def sync(self, subscription_id: UUID, *, trigger: str = "manual", skip_permission: bool = False) -> dict:
        sub = await self.session.get(SourceSubscription, subscription_id)
        if sub is None or sub.tenant_id != self.ctx.tenant_id:
            raise NotFoundError("Subscription not found")
        if sub.status == "paused":
            raise ValidationFailedError("Subscription is paused")
        source = await self._source(sub.source_id)
        if not skip_permission:
            self._require_owned_source(source)
        elif not can_manage_source(source, self.ctx):
            raise NotFoundError("Subscription not found")
        run = SyncRun(
            tenant_id=self.ctx.require_tenant(),
            subscription_id=sub.id,
            status="processing",
            trigger=trigger,
            started_at=datetime.now(UTC),
        )
        self.session.add(run)
        await self.session.flush()
        try:
            await self._run_sync(source, sub, run)
            run.status = "completed"
            run.completed_at = datetime.now(UTC)
            sub.last_sync_at = run.completed_at
            sub.last_error = None
            sub.next_sync_at = next_sync_at(sub.schedule)
            source.last_synced_at = run.completed_at
            source.last_error = None
            source.status = "connected"
        except Exception as exc:
            run.status = "failed"
            run.error_message = str(exc)
            run.completed_at = datetime.now(UTC)
            sub.last_error = str(exc)
            source.last_error = str(exc)
            source.status = "auth_expired" if isinstance(exc, ConnectorAuthExpiredError) else "sync_failed"
        await self.session.flush()
        return self._run_payload(run)

    def _run_payload(self, run: SyncRun) -> dict:
        return {
            "id": str(run.id),
            "subscription_id": str(run.subscription_id),
            "status": run.status,
            "trigger": run.trigger,
            "files_discovered": run.files_discovered,
            "files_added": run.files_added,
            "files_updated": run.files_updated,
            "files_deleted": run.files_deleted,
            "files_skipped": run.files_skipped,
            "files_failed": run.files_failed,
            "error_message": run.error_message,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        }

    async def sync_history(self, subscription_id: UUID) -> list[dict]:
        _sub, _source = await self._owned_subscription(subscription_id)
        rows = (
            await self.session.scalars(
                select(SyncRun)
                .where(SyncRun.subscription_id == subscription_id)
                .order_by(SyncRun.created_at.desc())
                .limit(20)
            )
        ).all()
        return [self._run_payload(r) for r in rows]

    async def _run_sync(self, source: DataSource, sub: SourceSubscription, run: SyncRun) -> None:
        config_extra = {
            "location_id": sub.external_location_id,
            "include_subfolders": sub.include_subfolders,
        }
        adapter = await self._adapter_for_source(source, config_extra)
        files = await adapter.list_files()
        allowed_ext = {str(x).lower().lstrip(".") for x in (sub.file_filters or [])}
        if allowed_ext:
            files = [f for f in files if (f.path.rsplit(".", 1)[-1].lower() in allowed_ext)]
        run.files_discovered = len(files)
        existing_rows = (
            await self.session.scalars(
                select(Document).where(
                    Document.source_id == source.id,
                    Document.subscription_id == sub.id,
                )
            )
        ).all()
        existing = {d.source_file_id: d for d in existing_rows}
        ingest = IngestionService(self.session, self.settings, self.ctx)
        seen: set[str] = set()
        for file in files:
            seen.add(file.source_file_id)
            try:
                content = await adapter.get_file(file.source_file_id)
            except Exception:
                run.files_failed += 1
                continue
            result = await ingest.ingest_content(
                source=source,
                source_file_id=file.source_file_id,
                filename=file.name or file.path.rsplit("/", 1)[-1],
                content=content,
                mime_type=file.mime_type or "text/plain",
                workspace_id=sub.workspace_id,
                subscription_id=sub.id,
                revision=file.revision,
                path=file.path,
                acl=sub.acl,
            )
            status = result.get("status")
            if status == "unchanged":
                run.files_skipped += 1
            elif status == "queued" and result.get("version_new"):
                run.files_updated += 1
            else:
                run.files_added += 1
            if result.get("job_id") and result.get("status") == "queued":
                await ingest.process_job(UUID(result["job_id"]))
        for fid, doc in existing.items():
            if fid not in seen:
                if doc.external_status != "deleted_externally":
                    run.files_deleted += 1
                doc.external_status = "deleted_externally"
                doc.active_version_id = None
        if run.files_deleted:
            await persist_authz_bump(self.session, self.ctx.require_tenant())
