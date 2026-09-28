from __future__ import annotations

import os
from pathlib import Path
from typing import Any, ClassVar
from uuid import UUID

from app.adapters.providers.connectors.files import INGEST_EXTS, mime_for
from app.application.sync_diff import diff_connector_files
from app.core.errors import ConnectorError, ValidationFailedError
from app.domain.ports.connector import DataSourceConnector
from app.domain.registry import register
from app.domain.types import (
    ConnectorCapabilities,
    ConnectorDefinition,
    ConnectorFile,
    ConnectorLocation,
    DocumentChange,
)

_SKIP_DIR_NAMES = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}


def _project_sources_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "configs" / "base.yaml").exists():
            return (parent / "data" / "sources").resolve()
    return (Path.cwd() / "data" / "sources").resolve()


def _user_source_root(tenant_id: UUID | str, user_id: UUID | str) -> Path:
    return (_project_sources_root() / str(tenant_id) / str(user_id)).resolve()


def _project_source_roots() -> list[Path]:
    seen: set[Path] = set()
    roots: list[Path] = []
    for path in (_project_sources_root(), Path.cwd() / "data" / "sources"):
        resolved = path.expanduser().resolve()
        if resolved not in seen:
            seen.add(resolved)
            roots.append(resolved)
    return roots


def _host_default_roots() -> list[Path]:
    """Host-wide folders for explicit host isolation (desktop overlay)."""
    seen: set[Path] = set()
    roots: list[Path] = []
    candidates = list(_project_source_roots())
    home = Path.home()
    for extra in (home / "Documents", home / "Desktop", home / "Downloads"):
        if extra.exists() and extra.is_dir():
            candidates.append(extra)
    for parent in Path(__file__).resolve().parents:
        demo = parent / "demo"
        if demo.is_dir() and (parent / "configs" / "base.yaml").exists():
            candidates.append(demo)
            break
    for raw in candidates:
        path = raw.expanduser().resolve()
        if path not in seen:
            seen.add(path)
            roots.append(path)
    return roots


def filesystem_roots(
    extra: list[str] | None = None,
    *,
    isolation: str = "user",
    tenant_id: UUID | str | None = None,
    user_id: UUID | str | None = None,
) -> list[Path]:
    raw = os.environ.get("CONNECTOR_FS_ROOTS", "")
    roots = [Path(part).expanduser().resolve() for part in raw.split(",") if part.strip()]
    for part in extra or []:
        text = str(part).strip()
        if text:
            path = Path(text).expanduser().resolve()
            if path not in roots:
                roots.append(path)
    mode = (isolation or "user").lower()
    if mode == "user" and tenant_id and user_id:
        user_root = _user_source_root(tenant_id, user_id)
        user_root.mkdir(parents=True, exist_ok=True)
        if user_root not in roots:
            roots.insert(0, user_root)
    if not roots:
        roots = _host_default_roots() if mode == "host" else _project_source_roots()
    return roots


def path_is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def resolve_allowed_path(
    path: str | Path,
    extra: list[str] | None = None,
    *,
    isolation: str = "user",
    tenant_id: UUID | str | None = None,
    user_id: UUID | str | None = None,
) -> Path:
    resolved = Path(path).expanduser().resolve()
    if resolved.is_symlink():
        resolved = resolved.resolve()
    for root in filesystem_roots(extra, isolation=isolation, tenant_id=tenant_id, user_id=user_id):
        if path_is_within(resolved, root):
            return resolved
    raise ValidationFailedError(
        "Folder is outside the allowed roots. Add the directory in Admin runtime settings or CONNECTOR_FS_ROOTS."
    )


def _folder_label(path: Path) -> str:
    home = Path.home().resolve()
    try:
        if path == (home / "Documents").resolve():
            return "Documents"
        if path == (home / "Desktop").resolve():
            return "Desktop"
        if path == (home / "Downloads").resolve():
            return "Downloads"
        if path.name == "demo" and (path.parent / "configs" / "base.yaml").exists():
            return "Demo files"
    except OSError:
        pass
    if path.name == "sources" and path.parent.name == "data":
        return "Project sources"
    return path.name or str(path)


def _visible_child_count(folder: Path) -> int:
    try:
        return sum(1 for child in folder.iterdir() if not child.name.startswith("."))
    except OSError:
        return 0


def _as_folder_item(path: Path, *, name: str | None = None) -> dict[str, Any]:
    return {
        "id": str(path),
        "name": name or _folder_label(path),
        "path": str(path),
        "kind": "folder",
        "child_count": _visible_child_count(path),
    }


def list_host_folders(
    path: str | None,
    extra: list[str] | None = None,
    *,
    isolation: str = "user",
    tenant_id: UUID | str | None = None,
    user_id: UUID | str | None = None,
) -> dict[str, Any]:
    fs_kwargs = {"isolation": isolation, "tenant_id": tenant_id, "user_id": user_id}
    roots = [root for root in filesystem_roots(extra, **fs_kwargs) if root.exists() and root.is_dir()]
    if not path:
        return {
            "path": None,
            "parent": None,
            "at_roots": True,
            "items": [_as_folder_item(root) for root in roots],
        }

    folder = resolve_allowed_path(path, extra, **fs_kwargs)
    if not folder.is_dir():
        raise ValidationFailedError("Not a folder")

    at_allowed_root = any(folder == root for root in filesystem_roots(extra, **fs_kwargs))
    parent = None if at_allowed_root else str(folder.parent)
    items: list[dict[str, Any]] = []
    try:
        children = sorted(folder.iterdir(), key=lambda child: (not child.is_dir(), child.name.lower()))
    except OSError as exc:
        raise ConnectorError(f"Cannot read folder: {folder}") from exc
    for child in children:
        if child.name.startswith(".") or child.name in _SKIP_DIR_NAMES:
            continue
        try:
            resolved_child = resolve_allowed_path(child, extra, **fs_kwargs)
        except ValidationFailedError:
            continue
        if not path_is_within(resolved_child, folder):
            continue
        if resolved_child.is_dir():
            items.append(_as_folder_item(resolved_child, name=child.name))
        elif resolved_child.is_file() and resolved_child.suffix.lower() in INGEST_EXTS:
            items.append(
                {"id": str(resolved_child), "name": child.name, "path": str(resolved_child), "kind": "file"}
            )
    return {"path": str(folder), "parent": parent, "at_roots": False, "items": items}


@register("connector", "local_fs")
class LocalFolderConnector(DataSourceConnector):
    """Reads a real directory on the API host. Identity is device+inode, so renames stay the same document."""

    definition: ClassVar[ConnectorDefinition] = ConnectorDefinition(
        id="local_fs",
        name="Local Folder",
        description="Pick a folder the API server can read. User isolation uses data/sources/{tenant}/{user}, not host Documents/Desktop/Downloads.",
        icon="folder",
        authentication="none",
        mock=False,
        capabilities=ConnectorCapabilities(browse=True, subscribe=True, incremental_sync=True, local_watch=False),
    )

    def _fs_kwargs(self) -> dict:
        cfg = self.config or {}
        extra = cfg.get("_fs_roots")
        return {
            "extra": extra if isinstance(extra, list) else None,
            "isolation": str(cfg.get("_fs_isolation") or "user"),
            "tenant_id": cfg.get("_tenant_id"),
            "user_id": cfg.get("_user_id"),
        }

    def _root(self) -> Path:
        kwargs = self._fs_kwargs()
        configured = (self.config or {}).get("root_path") or (self.config or {}).get("location_id")
        if not configured or configured == "root":
            roots = filesystem_roots(**kwargs)
            return roots[0]
        return resolve_allowed_path(configured, **kwargs)

    def _location(self, location_id: str | None) -> Path:
        kwargs = self._fs_kwargs()
        if not location_id or location_id == "root":
            return self._root()
        return resolve_allowed_path(location_id, **kwargs)

    def _file_id(self, path: Path) -> str:
        stat = path.stat()
        return f"{stat.st_dev}:{stat.st_ino}"

    def _contained(self, path: Path, folder: Path) -> Path | None:
        kwargs = self._fs_kwargs()
        try:
            resolved = resolve_allowed_path(path, **kwargs)
        except ValidationFailedError:
            return None
        if not path_is_within(resolved, folder.resolve()):
            return None
        return resolved

    async def get_file(self, source_file_id: str) -> bytes:
        folder = self._location((self.config or {}).get("location_id"))
        for path in folder.rglob("*"):
            contained = self._contained(path, folder)
            if contained is None or not contained.is_file() or contained.name.startswith("."):
                continue
            if self._file_id(contained) == source_file_id:
                return contained.read_bytes()
        raise ConnectorError(f"Unknown local file {source_file_id}")

    def _to_file(self, path: Path) -> ConnectorFile:
        stat = path.stat()
        rel = str(path)
        return ConnectorFile(
            source_file_id=self._file_id(path),
            path=rel,
            name=path.name,
            parent_id=str(path.parent),
            revision=str(int(stat.st_mtime_ns)),
            checksum=f"{stat.st_size}:{int(stat.st_mtime_ns)}",
            mime_type=mime_for(path),
            size_bytes=stat.st_size,
            modified_at=str(int(stat.st_mtime)),
        )

    async def connect(self) -> None:
        root = self._root()
        if not root.exists() or not root.is_dir():
            raise ConnectorError(f"Local folder does not exist: {root}")

    async def disconnect(self) -> None:
        return None

    async def list_locations(self, parent_id: str | None = None) -> list[ConnectorLocation]:
        folder = self._location(parent_id)
        if not folder.exists():
            raise ConnectorError(f"Folder not found: {folder}")
        items = []
        for child in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
            contained = self._contained(child, folder)
            if contained is None or not contained.is_dir() or contained.name.startswith("."):
                continue
            items.append(
                ConnectorLocation(
                    id=str(contained),
                    name=child.name,
                    path=str(contained),
                    parent_id=str(folder),
                    child_count=sum(1 for _ in contained.iterdir() if not _.name.startswith(".")),
                )
            )
        return items

    async def browse(self, location_id: str) -> list[ConnectorLocation | ConnectorFile]:
        folder = self._location(location_id)
        if not folder.exists():
            raise ConnectorError(f"Folder not found: {folder}")
        items: list[ConnectorLocation | ConnectorFile] = []
        for child in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
            if child.name.startswith("."):
                continue
            contained = self._contained(child, folder)
            if contained is None:
                continue
            if contained.is_dir():
                items.append(
                    ConnectorLocation(
                        id=str(contained),
                        name=child.name,
                        path=str(contained),
                        parent_id=str(folder),
                    )
                )
            elif contained.suffix.lower() in INGEST_EXTS:
                items.append(self._to_file(contained))
        return items

    async def list_files(self) -> list[ConnectorFile]:
        folder = self._location((self.config or {}).get("location_id"))
        include = bool((self.config or {}).get("include_subfolders", True))
        files: list[ConnectorFile] = []
        if include:
            iterator = folder.rglob("*")
        else:
            iterator = folder.iterdir()
        for path in iterator:
            contained = self._contained(path, folder)
            if (
                contained is None
                or not contained.is_file()
                or contained.name.startswith(".")
                or contained.suffix.lower() not in INGEST_EXTS
            ):
                continue
            files.append(self._to_file(contained))
        return files

    async def get_metadata(self, source_file_id: str) -> ConnectorFile:
        for file in await self.list_files():
            if file.source_file_id == source_file_id:
                return file
        raise ConnectorError(f"Unknown local file {source_file_id}")

    async def detect_changes(self, previous: list[ConnectorFile]) -> list[DocumentChange]:
        return diff_connector_files(previous, await self.list_files())

    async def health_check(self) -> dict[str, Any]:
        root = self._root()
        return {"status": "healthy" if root.exists() else "missing", "provider": "local_fs", "root": str(root)}
