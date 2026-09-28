# Connector architecture (as implemented)

Sources are **provider adapters**, registered with `@register("connector", name)`. There is no second plugin system.

## Real connectors (default catalog)

| ID | Auth | What it talks to |
| --- | --- | --- |
| `local_fs` | none | A directory on the **API host**. Identity is `st_dev:st_ino` so renames stay the same document. |
| `s3` | API keys / env | Live S3 or MinIO via boto3 (`list_objects_v2` / `get_object`). |
| `google_drive` | OAuth2 | Google Drive API v3 (list, download, Docs export). |
| `onedrive` | OAuth2 | Microsoft Graph `/me/drives` and item content. |
| `sharepoint` | OAuth2 | Same Graph client; libraries appear as drives. |
| `dropbox` | OAuth2 | Dropbox `files/list_folder` and `files/download`. |

Mocks (`mock_google_drive`, …) stay registered for tests. They appear in the catalog only when `RAG_CONNECTOR_MOCKS=1`.

## OAuth (real)

Generic helper: `backend/app/adapters/providers/connectors/oauth.py`

1. `POST /api/v1/connectors/oauth/start` stores `oauth_states` and returns the **provider** authorization URL.
2. The UI redirects the browser to Google / Microsoft / Dropbox.
3. The provider redirects to `http://127.0.0.1:5173/sources?code=&state=`.
4. `POST /api/v1/connectors/oauth/callback` exchanges the code, encrypts tokens, creates `data_sources`.

Redirect URI in the cloud console must match the UI origin (`http://127.0.0.1:5173/sources`).

Tokens are encrypted with `LocalTokenCipher`. They are injected into the adapter on browse/sync and refreshed when near expiry. They are never logged.

### Environment

```bash
GOOGLE_OAUTH_CLIENT_ID=
GOOGLE_OAUTH_CLIENT_SECRET=
MICROSOFT_OAUTH_CLIENT_ID=
MICROSOFT_OAUTH_CLIENT_SECRET=
DROPBOX_OAUTH_CLIENT_ID=
DROPBOX_OAUTH_CLIENT_SECRET=
CONNECTOR_FS_ROOTS=/absolute/path/the/server/may/read
```

If OAuth env vars are missing, the catalog marks the connector `configured: false` and start fails with a validation error.

## Local folder

A browser cannot watch an arbitrary client disk. `local_fs` reads a path **the API process can access**, constrained by `CONNECTOR_FS_ROOTS` (default: `$HOME` and `./data/sources`).

## S3

Uses `connector_config.bucket` / `prefix` / `endpoint_url`, or `S3_*` from the environment. Access keys in the create payload are stored encrypted, not in plaintext config.

## Sync

Subscribe to a folder, then initial sync. **Sync now** re-runs. `schedule` (`hourly`, `daily`, `every_30_minutes`) sets `next_sync_at`; the API process ticks due subscriptions about once a minute.

Identity is provider file id (inode, S3 key, Drive id, Graph item id, Dropbox id) — not filename.

Deleted externals keep document history (`external_status=deleted_externally`).
