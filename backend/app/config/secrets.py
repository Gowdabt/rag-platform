from __future__ import annotations

import os

from app.core.errors import SecretResolutionError

ENV_SCHEME = "secret://env/"


def is_secret_ref(value: object) -> bool:
    return isinstance(value, str) and value.startswith("secret://")


def resolve_secret(ref: str) -> str:
    if not ref.startswith(ENV_SCHEME):
        raise SecretResolutionError(f"Unsupported secret scheme in '{ref}'")
    var_name = ref.removeprefix(ENV_SCHEME)
    if not var_name or not var_name.replace("_", "").isalnum():
        raise SecretResolutionError(f"Invalid environment secret name in '{ref}'")
    value = os.environ.get(var_name)
    if value is None or value == "":
        raise SecretResolutionError(f"Environment variable '{var_name}' is not set")
    return value


def resolve_secrets(data: object) -> object:
    """Replace secret://env/… strings. Leaves non-secret values unchanged."""
    if is_secret_ref(data):
        return resolve_secret(str(data))
    if isinstance(data, dict):
        return {k: resolve_secrets(v) for k, v in data.items()}
    if isinstance(data, list):
        return [resolve_secrets(v) for v in data]
    return data
