from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.authz import document_acl_params, document_acl_sql
from app.application.content_address import LOGICAL_CHUNK_FROM
from app.application.query import tokens as query_tokens
from app.core.context import RequestContext
from app.core.errors import ValidationFailedError
from app.domain.ports.sparse_index import SparseIndex
from app.domain.registry import register
from app.domain.types import SparseDocument, VectorFilter, VectorHit


@register("sparse_index", "postgres_fts")
class PostgresFTSIndex(SparseIndex):
    def __init__(self, ctx: RequestContext, session: AsyncSession | None = None):
        super().__init__(ctx)
        self.session = session

    async def upsert(self, documents: list[SparseDocument]) -> None:
        return None

    async def search(self, query: str, *, top_k: int, filters: VectorFilter) -> list[VectorHit]:
        if filters.tenant_id is None:
            raise ValidationFailedError("tenant_id filter is required")
        if self.session is None:
            raise ValidationFailedError("FTS index requires a session")
        q = (query or "").strip()
        if not q:
            return []
        like = "%" + q.replace("\\", "").replace("%", "").replace("_", "")[:80] + "%"
        terms = [t for t in query_tokens(q) if len(t) >= 3][:6]
        term_clause = ""
        params: dict = {"q": q, "like": like, "tenant": str(filters.tenant_id), "k": top_k}
        for i, term in enumerate(terms):
            key = f"t{i}"
            params[key] = f"%{term}%"
            term_clause += f" OR d.title ILIKE :{key} OR d.path ILIKE :{key}"
        sql = f"""
            SELECT c.id, d.id, v.id,
                   GREATEST(
                     COALESCE(ts_rank(c.search_vector, plainto_tsquery('english', :q)), 0),
                     CASE WHEN d.title ILIKE :like OR d.path ILIKE :like THEN 0.85 ELSE 0 END
                   ) AS score
            {LOGICAL_CHUNK_FROM}
            WHERE c.tenant_id = :tenant
              AND d.tenant_id = :tenant
              AND (
                    c.search_vector @@ plainto_tsquery('english', :q)
                    OR d.title ILIKE :like
                    OR d.path ILIKE :like
                    {term_clause}
                  )
        """
        if filters.workspace_id:
            sql += " AND d.workspace_id = :workspace"
            params["workspace"] = str(filters.workspace_id)
        if filters.version_id:
            sql += " AND v.id = :version"
            params["version"] = str(filters.version_id)
        sql += document_acl_sql("d")
        params.update(document_acl_params(filters))
        sql += " ORDER BY score DESC LIMIT :k"
        try:
            async with self.session.begin_nested():
                rows = (await self.session.execute(text(sql), params)).all()
        except Exception:
            return []
        return [
            VectorHit(chunk_id=r[0], document_id=r[1], version_id=r[2], score=float(r[3] or 0), payload={})
            for r in rows
        ]

    async def delete(self, chunk_ids: list[UUID], *, filters: VectorFilter) -> None:
        return None
