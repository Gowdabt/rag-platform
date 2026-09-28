from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.db.models import (
    EvaluationDataset,
    EvaluationItem,
    EvaluationResult,
    EvaluationRun,
)
from app.application.chat import ChatService
from app.config.models import PlatformSettings
from app.core.context import RequestContext
from app.core.errors import NotFoundError


def _tokens(text: str) -> set[str]:
    return {part for t in text.lower().split() if (part := t.strip(".,;:()[]{}\"'"))}


def lexical_f1(expected: str | None, actual: str | None) -> float:
    if not expected:
        return 1.0
    exp = _tokens(expected)
    act = _tokens(actual or "")
    if not exp:
        return 1.0
    if not act:
        return 0.0
    overlap = len(exp & act)
    precision = overlap / len(act)
    recall = overlap / len(exp)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def _names(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        names = []
        for item in value:
            names.extend(_names(item))
        return names
    if isinstance(value, dict):
        collected = []
        for key in ("name", "document_name", "title", "id", "document_id"):
            if value.get(key):
                collected.append(str(value[key]))
        if collected:
            return collected
        return [str(v) for v in value.values() if isinstance(v, str)]
    return [str(value)]


def citation_recall(expected_sources, actual_sources) -> float:
    expected = _names(expected_sources)
    if not expected:
        return 1.0
    actual = [n.lower() for n in _names(actual_sources)]
    hits = 0
    for name in expected:
        needle = name.lower()
        if any(needle in hay or hay in needle for hay in actual):
            hits += 1
    return hits / len(expected)


def score_item(
    *,
    expected_answer: str | None,
    actual_answer: str | None,
    expected_sources=None,
    actual_sources=None,
) -> dict:
    f1 = lexical_f1(expected_answer, actual_answer)
    recall = citation_recall(expected_sources, actual_sources)
    contains = bool(expected_answer) and expected_answer.lower() in (actual_answer or "").lower()
    return {
        "lexical_f1": round(f1, 4),
        "citation_recall": round(recall, 4),
        "answer_contains_expected": contains,
        "score": round((f1 + recall) / 2, 4),
    }


class EvalService:
    def __init__(self, session: AsyncSession, settings: PlatformSettings, ctx: RequestContext):
        self.session = session
        self.settings = settings
        self.ctx = ctx

    async def create_dataset(self, *, name: str, description: str | None = None) -> dict:
        row = EvaluationDataset(
            tenant_id=self.ctx.tenant_id, name=name, description=description
        )
        self.session.add(row)
        await self.session.flush()
        return {"id": str(row.id), "name": row.name, "description": row.description}

    async def list_datasets(self, *, limit: int = 100, offset: int = 0) -> list[dict]:
        from app.api.pagination import clip_limit, clip_offset

        rows = (
            await self.session.scalars(
                select(EvaluationDataset)
                .where(EvaluationDataset.tenant_id == self.ctx.tenant_id)
                .offset(clip_offset(offset))
                .limit(clip_limit(limit))
            )
        ).all()
        return [{"id": str(r.id), "name": r.name, "description": r.description} for r in rows]

    async def add_item(
        self,
        dataset_id: UUID,
        *,
        question: str,
        expected_answer: str | None = None,
        expected_sources: list | dict | None = None,
    ) -> dict:
        dataset = await self.session.get(EvaluationDataset, dataset_id)
        if dataset is None or dataset.tenant_id != self.ctx.tenant_id:
            raise NotFoundError("Dataset not found")
        item = EvaluationItem(
            tenant_id=self.ctx.tenant_id,
            dataset_id=dataset_id,
            question=question,
            expected_answer=expected_answer,
            expected_sources=expected_sources or [],
        )
        self.session.add(item)
        await self.session.flush()
        return {
            "id": str(item.id),
            "dataset_id": str(dataset_id),
            "question": item.question,
        }

    async def list_items(self, dataset_id: UUID) -> list[dict]:
        rows = (
            await self.session.scalars(
                select(EvaluationItem).where(
                    EvaluationItem.tenant_id == self.ctx.tenant_id,
                    EvaluationItem.dataset_id == dataset_id,
                )
            )
        ).all()
        return [
            {
                "id": str(r.id),
                "question": r.question,
                "expected_answer": r.expected_answer,
                "expected_sources": r.expected_sources,
            }
            for r in rows
        ]

    async def run_dataset(self, dataset_id: UUID, *, workspace_id: UUID | None = None) -> dict:
        dataset = await self.session.get(EvaluationDataset, dataset_id)
        if dataset is None or dataset.tenant_id != self.ctx.tenant_id:
            raise NotFoundError("Dataset not found")
        items = (
            await self.session.scalars(
                select(EvaluationItem).where(
                    EvaluationItem.tenant_id == self.ctx.tenant_id,
                    EvaluationItem.dataset_id == dataset_id,
                )
            )
        ).all()
        run = EvaluationRun(
            tenant_id=self.ctx.tenant_id,
            dataset_id=dataset_id,
            config_snapshot={
                "llm": self.settings.llm.provider,
                "embedding": self.settings.embedding.provider,
                "retrieval": self.settings.retrieval.strategy,
            },
            status="running",
            started_at=datetime.now(UTC),
        )
        self.session.add(run)
        await self.session.flush()

        chat = ChatService(self.session, self.settings, self.ctx)
        scores: list[float] = []
        for item in items:
            result = await chat.ask(
                question=item.question,
                workspace_id=workspace_id or self.ctx.workspace_id,
                include_history=False,
            )
            metrics = score_item(
                expected_answer=item.expected_answer,
                actual_answer=result.get("answer"),
                expected_sources=item.expected_sources,
                actual_sources=result.get("citations") or [],
            )
            scores.append(float(metrics["score"]))
            self.session.add(
                EvaluationResult(
                    tenant_id=self.ctx.tenant_id,
                    run_id=run.id,
                    item_id=item.id,
                    metrics=metrics,
                    actual_answer=result.get("answer"),
                    actual_sources=result.get("citations") or [],
                )
            )
        run.status = "completed"
        run.finished_at = datetime.now(UTC)
        await self.session.flush()
        mean = round(sum(scores) / len(scores), 4) if scores else None
        return await self.get_run(run.id, mean_score=mean)

    async def list_runs(self, dataset_id: UUID | None = None) -> list[dict]:
        stmt = select(EvaluationRun).where(EvaluationRun.tenant_id == self.ctx.tenant_id)
        if dataset_id:
            stmt = stmt.where(EvaluationRun.dataset_id == dataset_id)
        rows = (await self.session.scalars(stmt)).all()
        return [
            {
                "id": str(r.id),
                "dataset_id": str(r.dataset_id),
                "status": r.status,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            }
            for r in rows
        ]

    async def get_run(self, run_id: UUID, mean_score: float | None = None) -> dict:
        run = await self.session.get(EvaluationRun, run_id)
        if run is None or run.tenant_id != self.ctx.tenant_id:
            raise NotFoundError("Run not found")
        results = (
            await self.session.scalars(
                select(EvaluationResult).where(
                    EvaluationResult.tenant_id == self.ctx.tenant_id,
                    EvaluationResult.run_id == run_id,
                )
            )
        ).all()
        metrics = [r.metrics for r in results]
        if mean_score is None and metrics:
            mean_score = round(
                sum(float(m.get("score") or 0) for m in metrics) / len(metrics), 4
            )
        return {
            "id": str(run.id),
            "dataset_id": str(run.dataset_id),
            "status": run.status,
            "mean_score": mean_score,
            "config_snapshot": run.config_snapshot,
            "results": [
                {
                    "item_id": str(r.item_id),
                    "metrics": r.metrics,
                    "actual_answer": r.actual_answer,
                    "actual_sources": r.actual_sources,
                }
                for r in results
            ],
        }
