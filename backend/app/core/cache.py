from __future__ import annotations

from collections import OrderedDict
from threading import Lock
from uuid import UUID


def _assert_scoped_key(key: str) -> None:
    parts = str(key).split(":")
    if len(parts) < 4 or not parts[0] or not parts[1]:
        raise ValueError("cache keys must include tenant, user, and authz epoch")


class TenantCache:
    """Process-local LRU. Keys must include tenant, user, and the PostgreSQL authz epoch — never the query alone.

    Epochs live in `tenants.authz_epoch` / `users.authz_epoch` so role/share/disable/suspend
    bumps are visible to every worker. Pass `authz_epoch=await load_authz_epoch(...)` into
    get/set; process-local `epoch()` is only a fallback for unit tests without a session.
    """

    def __init__(self, max_items: int = 2048):
        self._data: OrderedDict[str, object] = OrderedDict()
        self._epochs: dict[str, int] = {}
        self._max = max_items
        self._lock = Lock()

    def get(self, key: str):
        _assert_scoped_key(key)
        with self._lock:
            if key not in self._data:
                return None
            self._data.move_to_end(key)
            return self._data[key]

    def set(self, key: str, value: object) -> None:
        _assert_scoped_key(key)
        with self._lock:
            self._data[key] = value
            self._data.move_to_end(key)
            while len(self._data) > self._max:
                self._data.popitem(last=False)

    def epoch(self, tenant_id: UUID | str, user_id: UUID | str | None = None) -> int:
        tenant_key = str(tenant_id)
        tenant_epoch = self._epochs.get(tenant_key, 0)
        if user_id:
            return tenant_epoch + self._epochs.get(f"{tenant_key}:{user_id}", 0)
        return tenant_epoch

    def bump(self, tenant_id: UUID | str, user_id: UUID | str | None = None) -> int:
        """Invalidate cached answers after role, share, disable, or suspend changes."""
        tenant_key = str(tenant_id)
        with self._lock:
            if user_id:
                user_key = f"{tenant_key}:{user_id}"
                self._epochs[user_key] = self._epochs.get(user_key, 0) + 1
                prefix = f"{tenant_key}:{user_id}:"
                drop = [k for k in self._data if k.startswith(prefix)]
            else:
                self._epochs[tenant_key] = self._epochs.get(tenant_key, 0) + 1
                prefix = f"{tenant_key}:"
                drop = [k for k in self._data if k.startswith(prefix)]
            for key in drop:
                self._data.pop(key, None)
        return self.epoch(tenant_id, user_id)

    def scoped_key(
        self,
        tenant_id: UUID | str,
        key: str,
        *,
        user_id: UUID | str | None = None,
        authz_epoch: int | None = None,
    ) -> str:
        if not tenant_id:
            raise ValueError("tenant_id is required for cache keys")
        if not user_id:
            raise ValueError("user_id is required for cache keys")
        epoch = self.epoch(tenant_id, user_id) if authz_epoch is None else int(authz_epoch)
        return f"{tenant_id}:{user_id}:{epoch}:{key}"

    def get_tenant(
        self,
        tenant_id: UUID | str,
        key: str,
        *,
        user_id: UUID | str | None = None,
        authz_epoch: int | None = None,
    ):
        return self.get(self.scoped_key(tenant_id, key, user_id=user_id, authz_epoch=authz_epoch))

    def set_tenant(
        self,
        tenant_id: UUID | str,
        key: str,
        value: object,
        *,
        user_id: UUID | str | None = None,
        authz_epoch: int | None = None,
    ) -> None:
        self.set(self.scoped_key(tenant_id, key, user_id=user_id, authz_epoch=authz_epoch), value)


cache = TenantCache()
