from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, urlencode

import httpx

from app.core.crypto import LocalTokenCipher
from app.core.errors import ConnectorAuthExpiredError, ConnectorError, ValidationFailedError
from app.domain.ports.connector import DataSourceConnector
from app.domain.types import ConnectorAuthResult

_TIMEOUT = httpx.Timeout(30.0)


@dataclass(frozen=True)
class OAuthProvider:
    id: str
    authorize_url: str
    token_url: str
    client_id_env: str
    client_secret_env: str
    scopes: tuple[str, ...]
    revoke_url: str | None = None
    extra_authorize: dict[str, str] = field(default_factory=dict)
    extra_token: dict[str, str] = field(default_factory=dict)


OAUTH_PROVIDERS: dict[str, OAuthProvider] = {
    "google_drive": OAuthProvider(
        id="google_drive",
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        revoke_url="https://oauth2.googleapis.com/revoke",
        client_id_env="GOOGLE_OAUTH_CLIENT_ID",
        client_secret_env="GOOGLE_OAUTH_CLIENT_SECRET",
        scopes=(
            "https://www.googleapis.com/auth/drive.readonly",
            "https://www.googleapis.com/auth/userinfo.email",
        ),
        extra_authorize={"access_type": "offline", "prompt": "consent", "include_granted_scopes": "true"},
    ),
    "onedrive": OAuthProvider(
        id="onedrive",
        authorize_url="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        token_url="https://login.microsoftonline.com/common/oauth2/v2.0/token",
        client_id_env="MICROSOFT_OAUTH_CLIENT_ID",
        client_secret_env="MICROSOFT_OAUTH_CLIENT_SECRET",
        scopes=("offline_access", "User.Read", "Files.Read", "Files.Read.All", "Sites.Read.All"),
        extra_authorize={"prompt": "select_account", "response_mode": "query"},
    ),
    "sharepoint": OAuthProvider(
        id="sharepoint",
        authorize_url="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        token_url="https://login.microsoftonline.com/common/oauth2/v2.0/token",
        client_id_env="MICROSOFT_OAUTH_CLIENT_ID",
        client_secret_env="MICROSOFT_OAUTH_CLIENT_SECRET",
        scopes=("offline_access", "User.Read", "Files.Read.All", "Sites.Read.All"),
        extra_authorize={"prompt": "select_account", "response_mode": "query"},
    ),
    "dropbox": OAuthProvider(
        id="dropbox",
        authorize_url="https://www.dropbox.com/oauth2/authorize",
        token_url="https://api.dropboxapi.com/oauth2/token",
        client_id_env="DROPBOX_OAUTH_CLIENT_ID",
        client_secret_env="DROPBOX_OAUTH_CLIENT_SECRET",
        extra_authorize={"token_access_type": "offline"},
        scopes=("files.metadata.read", "files.content.read", "account_info.read"),
    ),
}


_ENC_PREFIX = "enc:"
_LOCAL_REDIRECT_HOSTS = {"127.0.0.1", "localhost"}


def encrypt_secret(value: str) -> str:
    raw = (value or "").strip()
    if not raw or raw.startswith(_ENC_PREFIX):
        return raw
    return _ENC_PREFIX + LocalTokenCipher().encrypt(raw)


def decrypt_secret(value: str) -> str:
    raw = value or ""
    if raw.startswith(_ENC_PREFIX):
        return LocalTokenCipher().decrypt(raw[len(_ENC_PREFIX) :])
    return raw


def assert_oauth_redirect_uri(redirect_uri: str) -> str:
    from urllib.parse import urlparse

    parsed = urlparse((redirect_uri or "").strip())
    if parsed.scheme != "http" or (parsed.hostname or "") not in _LOCAL_REDIRECT_HOSTS:
        raise ValidationFailedError("OAuth redirect must be http://127.0.0.1 or http://localhost")
    if parsed.path.rstrip("/") != "/sources":
        raise ValidationFailedError("OAuth redirect path must be /sources")
    return redirect_uri.strip()


PROVIDER_GROUP = {
    "google_drive": "google",
    "onedrive": "microsoft",
    "sharepoint": "microsoft",
    "dropbox": "dropbox",
}

_GROUP_ENV = {
    "google": ("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET"),
    "microsoft": ("MICROSOFT_OAUTH_CLIENT_ID", "MICROSOFT_OAUTH_CLIENT_SECRET"),
    "dropbox": ("DROPBOX_OAUTH_CLIENT_ID", "DROPBOX_OAUTH_CLIENT_SECRET"),
}


def oauth_provider(connector_id: str) -> OAuthProvider | None:
    return OAUTH_PROVIDERS.get(connector_id)


def _pair(spec: OAuthProvider, clients: dict | None = None) -> tuple[str, str]:
    group = PROVIDER_GROUP.get(spec.id)
    overlay = ((clients or {}).get(group) or {}) if group else {}
    overlay_id = str(overlay.get("client_id") or "").strip()
    overlay_secret = decrypt_secret(str(overlay.get("client_secret") or "").strip())
    env_id = os.environ.get(spec.client_id_env, "").strip()
    env_secret = os.environ.get(spec.client_secret_env, "").strip()
    return overlay_id or env_id, overlay_secret or env_secret


def oauth_is_configured(connector_id: str, clients: dict | None = None) -> bool:
    spec = oauth_provider(connector_id)
    if spec is None:
        return False
    client_id, client_secret = _pair(spec, clients)
    return bool(client_id and client_secret)


def _credentials(spec: OAuthProvider, clients: dict | None = None) -> tuple[str, str]:
    client_id, client_secret = _pair(spec, clients)
    if not client_id or not client_secret:
        group = PROVIDER_GROUP.get(spec.id, spec.id)
        raise ValidationFailedError(
            f"{spec.id} is not configured. Save the {group} OAuth client at runtime on Sources, "
            f"or optionally set {spec.client_id_env}."
        )
    return client_id, client_secret


def build_authorization_url(
    connector_id: str, *, redirect_uri: str, state: str, clients: dict | None = None
) -> str:
    spec = oauth_provider(connector_id)
    if spec is None:
        raise ValidationFailedError(f"No OAuth provider for {connector_id}")
    client_id, _ = _credentials(spec, clients)
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "state": state,
        **spec.extra_authorize,
    }
    if spec.scopes:
        params["scope"] = " ".join(spec.scopes)
    return f"{spec.authorize_url}?{urlencode(params, quote_via=quote)}"


async def exchange_code(
    connector_id: str, *, code: str, redirect_uri: str, clients: dict | None = None
) -> ConnectorAuthResult:
    spec = oauth_provider(connector_id)
    if spec is None:
        raise ValidationFailedError(f"No OAuth provider for {connector_id}")
    client_id, client_secret = _credentials(spec, clients)
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "client_secret": client_secret,
        **spec.extra_token,
    }
    return await _token_request(spec, data)


async def refresh_access_token(
    connector_id: str, refresh_token: str, clients: dict | None = None
) -> ConnectorAuthResult:
    spec = oauth_provider(connector_id)
    if spec is None:
        raise ValidationFailedError(f"No OAuth provider for {connector_id}")
    client_id, client_secret = _credentials(spec, clients)
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
        **spec.extra_token,
    }
    result = await _token_request(spec, data)
    if not result.refresh_token:
        result = result.model_copy(update={"refresh_token": refresh_token})
    return result


def oauth_clients_status(clients: dict | None = None) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for group, (id_env, secret_env) in _GROUP_ENV.items():
        env_id = os.environ.get(id_env, "").strip()
        env_secret = os.environ.get(secret_env, "").strip()
        overlay = ((clients or {}).get(group) or {}) if isinstance(clients, dict) else {}
        client_id = str(overlay.get("client_id") or "").strip() or env_id
        secret = decrypt_secret(str(overlay.get("client_secret") or "").strip()) or env_secret
        out[group] = {
            "client_id": client_id,
            "configured": bool(client_id and secret),
            "from_env": bool(env_id and env_secret),
            "has_secret": bool(secret),
        }
    return out


async def fetch_account_label(connector_id: str, access_token: str) -> str | None:
    if not access_token:
        return None
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            if connector_id == "google_drive":
                resp = await client.get("https://www.googleapis.com/oauth2/v2/userinfo", headers=headers)
                if resp.status_code < 400:
                    return resp.json().get("email")
            elif connector_id in {"onedrive", "sharepoint"}:
                resp = await client.get("https://graph.microsoft.com/v1.0/me", headers=headers)
                if resp.status_code < 400:
                    data = resp.json()
                    return data.get("userPrincipalName") or data.get("mail") or data.get("displayName")
            elif connector_id == "dropbox":
                resp = await client.post(
                    "https://api.dropboxapi.com/2/users/get_current_account", headers=headers
                )
                if resp.status_code < 400:
                    data = resp.json()
                    return data.get("email") or (data.get("name") or {}).get("display_name")
    except httpx.HTTPError:
        return None
    return None


async def revoke_token(connector_id: str, token: str) -> None:
    spec = oauth_provider(connector_id)
    if spec is None or not spec.revoke_url or not token:
        return
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        await client.post(spec.revoke_url, data={"token": token})


async def _token_request(spec: OAuthProvider, data: dict[str, Any]) -> ConnectorAuthResult:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            resp = await client.post(spec.token_url, data=data)
        except httpx.HTTPError as exc:
            raise ConnectorError(f"{spec.id} token request failed") from exc
    if resp.status_code in {400, 401}:
        raise ConnectorAuthExpiredError(f"{spec.id} authorization was denied or expired")
    if resp.status_code >= 400:
        raise ConnectorError(f"{spec.id} token exchange failed ({resp.status_code})")
    payload = resp.json()
    access = payload.get("access_token")
    if not access:
        raise ConnectorAuthExpiredError(f"{spec.id} did not return an access token")
    return ConnectorAuthResult(
        access_token=access,
        refresh_token=payload.get("refresh_token"),
        expires_in=int(payload.get("expires_in") or 3600),
        scopes=str(payload.get("scope") or "").split(),
    )


class OAuthConnectorMixin(DataSourceConnector):
    oauth_id: str

    def _token(self) -> str:
        token = (self.config or {}).get("access_token")
        if not token:
            raise ConnectorAuthExpiredError("Missing access token. Reconnect this source.")
        return token

    def _oauth_clients(self) -> dict | None:
        clients = (self.config or {}).get("_oauth_clients")
        return clients if isinstance(clients, dict) else None

    async def authorization_url(self, *, redirect_uri: str, state: str) -> str | None:
        return build_authorization_url(
            self.oauth_id, redirect_uri=redirect_uri, state=state, clients=self._oauth_clients()
        )

    async def authenticate(self, credentials: dict[str, Any]) -> ConnectorAuthResult:
        code = credentials.get("code")
        redirect_uri = credentials.get("redirect_uri") or ""
        if not code:
            raise ConnectorAuthExpiredError("Missing authorization code")
        result = await exchange_code(
            self.oauth_id, code=code, redirect_uri=redirect_uri, clients=self._oauth_clients()
        )
        if result.account_label:
            return result
        label = await fetch_account_label(self.oauth_id, result.access_token)
        return result.model_copy(update={"account_label": label}) if label else result

    async def refresh_authentication(self, refresh_token: str) -> ConnectorAuthResult:
        return await refresh_access_token(self.oauth_id, refresh_token, clients=self._oauth_clients())

    async def connect(self) -> None:
        self._token()

    async def disconnect(self) -> None:
        token = (self.config or {}).get("access_token")
        if token:
            await revoke_token(self.oauth_id, token)
