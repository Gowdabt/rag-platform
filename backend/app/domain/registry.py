from __future__ import annotations

from collections.abc import Callable
from importlib.metadata import entry_points
from typing import Any, TypeVar

from app.core.errors import ProviderNotImplementedError, UnknownProviderError

Factory = Callable[..., Any]
T = TypeVar("T")

_ENTRY_POINT_GROUP = "rag_platform.providers"
_entry_points_loaded = False


class ProviderRegistry:
    def __init__(self) -> None:
        self._factories: dict[tuple[str, str], Factory] = {}

    def register(self, kind: str, name: str, factory: Factory) -> None:
        self._factories[(kind, name)] = factory

    def get(self, kind: str, name: str) -> Factory:
        _ensure_entry_points()
        factory = self._factories.get((kind, name))
        if factory is None:
            raise ProviderNotImplementedError(
                f"Provider '{kind}:{name}' is known or requested but has no registered "
                "implementation. Add an adapter and @register() it."
            )
        return factory

    def create(self, kind: str, name: str, *args: Any, **kwargs: Any) -> Any:
        return self.get(kind, name)(*args, **kwargs)

    def contains(self, kind: str, name: str) -> bool:
        _ensure_entry_points()
        return (kind, name) in self._factories

    def registered(self, kind: str | None = None) -> list[tuple[str, str]]:
        _ensure_entry_points()
        items = list(self._factories)
        if kind is None:
            return items
        return [item for item in items if item[0] == kind]


registry = ProviderRegistry()


def register(kind: str, name: str) -> Callable[[T], T]:
    def decorator(factory: T) -> T:
        registry.register(kind, name, factory)
        return factory

    return decorator


def _ensure_entry_points() -> None:
    global _entry_points_loaded
    if _entry_points_loaded:
        return
    _entry_points_loaded = True
    try:
        selected = entry_points().select(group=_ENTRY_POINT_GROUP)
    except Exception:
        return
    for ep in selected:
        ep.load()


def require_known_or_raise(kind: str, name: str, known: frozenset[str]) -> None:
    if name not in known:
        raise UnknownProviderError(
            f"Unknown {kind} provider '{name}'. Known: {sorted(known)}"
        )
