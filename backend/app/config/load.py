from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import ValidationError

from app.config.merge import assert_overlay_allowed, deep_merge
from app.config.models import PlatformSettings
from app.config.secrets import resolve_secrets
from app.core.errors import ConfigError, UnknownProviderError

_ENV_FILES_LOADED = False


def _load_dotenv() -> None:
    global _ENV_FILES_LOADED
    if _ENV_FILES_LOADED:
        return
    load_dotenv()
    for parent in Path(__file__).resolve().parents:
        env_file = parent / ".env"
        if env_file.exists():
            load_dotenv(env_file, override=False)
            break
    _ENV_FILES_LOADED = True


def config_dir() -> Path:
    raw = os.environ.get("RAG_CONFIG_DIR")
    if raw:
        path = Path(raw)
        if not path.is_absolute():
            path = Path.cwd() / path
        if (path / "base.yaml").exists():
            return path.resolve()
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "configs"
        if (candidate / "base.yaml").exists():
            return candidate
    raise ConfigError(
        "Could not find configs/base.yaml. Set RAG_CONFIG_DIR to the configs directory."
    )


def environment_name() -> str:
    return os.environ.get("RAG_ENV", "development")


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Configuration file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"Configuration file must be a mapping: {path}")
    return data


def load_yaml_layers(env: str | None = None) -> dict[str, Any]:
    env_name = env or environment_name()
    root = config_dir()
    base = _read_yaml(root / "base.yaml")
    env_file = root / f"{env_name}.yaml"
    if not env_file.exists():
        raise ConfigError(f"Unknown environment '{env_name}' (missing {env_file})")
    return deep_merge(base, _read_yaml(env_file))


def apply_overlays(
    base: dict[str, Any],
    overlays: list[tuple[str, dict[str, Any]]],
) -> dict[str, Any]:
    current = dict(base)
    for scope, overlay in overlays:
        if not overlay:
            continue
        assert_overlay_allowed(overlay, scope)
        current = deep_merge(current, overlay)
    return current


def parse_settings(data: dict[str, Any], *, resolve: bool = False) -> PlatformSettings:
    payload = resolve_secrets(data) if resolve else data
    if not isinstance(payload, dict):
        raise ConfigError("Resolved configuration is not a mapping")
    try:
        return PlatformSettings.model_validate(payload)
    except ValidationError as exc:
        message = str(exc)
        if "Unknown" in message and "provider" in message:
            raise UnknownProviderError(message) from exc
        raise ConfigError(message) from exc


def load_platform_settings(
    *,
    env: str | None = None,
    overlays: list[tuple[str, dict[str, Any]]] | None = None,
    resolve: bool = False,
) -> PlatformSettings:
    """Load and validate platform configuration.

    `resolve=False` keeps secret:// refs as strings (tests, overlay validation).
    `resolve=True` requires environment variables to be present.
    """
    _load_dotenv()
    data = load_yaml_layers(env)
    if overlays:
        data = apply_overlays(data, overlays)
    return parse_settings(data, resolve=resolve)
