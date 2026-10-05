#!/usr/bin/env python3
"""Idempotent Northline Software demo seed.

Creates a real tenant, three users, and research documents through the same
signup, invite, upload, and chat paths the app uses. Re-running resets the
demo passwords and skips documents and questions that are already present.

    backend/.venv/bin/python scripts/seed_demo.py
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

SLUG = "northline-software"
TENANT_NAME = "Northline Software"
PASSWORD = "Northline-demo-1"
API = "http://127.0.0.1:8000"

ADMIN = ("daniel.okada@northline.demo", "Daniel Okada", "Tenant Admin")
MEMBER = ("priya.shah@northline.demo", "Priya Shah", "Member")
VIEWER = ("samira.holt@northline.demo", "Samira Holt", "Viewer")

DOC_STANDARD = "Research Citation Standard.txt"
DOC_PRIVATE = "Helios Bank Retrieval Notes.txt"

STANDARD_QUESTION = (
    "Which embedding model does the research citation standard require for shared "
    "write-ups, and what three parts must a finding include before the whole team can use it?"
)
PRIVATE_QUESTION = (
    "What citation-miss reduction did the Helios Bank retrieval pilot measure, "
    "and which reranker model produced it?"
)

# Strings that must never appear in an answer for someone who cannot read the private notes.
PRIVATE_LEAKS = ("41.7", "helios", "rerank-b3")

STANDARD_BODY = """Northline Software
Research Citation Standard
Author: Daniel Okada, Senior Member of Technical Staff
Audience: everyone in the Northline Software tenant

Section 1. Embedding model for shared write-ups
The required embedding model for shared write-ups is northline-embed-v2. A research note that was embedded with any other model is not cited as a team standard. Members and viewers may read this standard and ask questions about it.

Section 2. Ready for the whole team
A finding is ready for the whole team only when it has a method section, a measured result, and a named owner. Until those three parts are in the write-up, the note stays with its author on Only me. Publishing to everyone in this tenant is a separate choice from drafting the note.

Section 3. What this standard does not contain
This standard does not name design-partner customers, unpublished pilot percentages, or unreleased reranker model names. Those stay in the author's private research notes. Do not copy an unreleased customer pilot into this file.

Section 4. How answers are cited
When someone asks in chat, the answer may cite only this standard and other files that person is allowed to read. If a passage is missing from the answer, it was not in that person's library.
"""

PRIVATE_BODY = """Northline Software
Helios Bank Retrieval Notes
Author: Priya Shah, Member of Technical Staff
Visibility: only Priya Shah. Not for the Tenant Admin. Not for Viewers. Not for the rest of the tenant.

These are early research notes. They are not the research citation standard. Leave Visible to on Only me.

The unpublished customer is Helios Bank. In the March retrieval pilot on the Helios Bank support corpus (12,400 questions, held-out week of 2026-03-09), switching the reranker from the default cross-encoder to northline-rerank-b3 cut citation misses. The unpublished citation-miss reduction is 41.7 percent. The unpublished reranker is northline-rerank-b3.

Priya Shah has not shared the 41.7 percent figure, the model name northline-rerank-b3, or the customer name Helios Bank with Daniel Okada or Samira Holt. This pilot is not approved for tenant-wide research use.
"""


def _title_key(question: str) -> str:
    return question[:80]


async def ensure_people() -> None:
    from sqlalchemy import select

    from app.adapters.db.models import Tenant, TenantMembership, User
    from app.adapters.db.rls import apply_rls_ids
    from app.adapters.db.session import dispose_engine, init_engine, session_factory
    from app.application.identity import IdentityService
    from app.config.load import load_platform_settings
    from app.core.context import RequestContext
    from app.core.errors import ConflictError
    from app.core.security import hash_password

    settings = load_platform_settings(resolve=True)
    init_engine(settings)
    try:
        factory = session_factory()
        async with factory() as session:
            async with session.begin():
                identity = IdentityService(session, settings)
                tenant = await session.scalar(select(Tenant).where(Tenant.slug == SLUG))
                if tenant is None:
                    existing_admin = await session.scalar(select(User).where(User.email == ADMIN[0]))
                    if existing_admin is not None:
                        raise SystemExit(
                            f"{ADMIN[0]} already exists but tenant {SLUG} does not. "
                            "Refusing to create a second account."
                        )
                    await identity.signup(email=ADMIN[0], password=PASSWORD, tenant_name=TENANT_NAME)
                    tenant = await session.scalar(select(Tenant).where(Tenant.slug == SLUG))
                    if tenant is None:
                        raise SystemExit(f"Signup did not create tenant slug {SLUG}")
                    print(f"Created tenant {tenant.name} ({tenant.slug})")
                else:
                    print(f"Tenant already present: {tenant.name} ({tenant.slug})")

                admin = await session.scalar(select(User).where(User.email == ADMIN[0]))
                if admin is None:
                    raise SystemExit(f"Missing admin user {ADMIN[0]}")
                await apply_rls_ids(session, tenant_id=tenant.id, user_id=admin.id)
                admin.display_name = ADMIN[1]
                admin.password_hash = hash_password(PASSWORD)
                admin.status = "active"
                await session.flush()

                admin_ctx = await identity.hydrate_context(
                    RequestContext(
                        request_id="seed-demo",
                        tenant_id=tenant.id,
                        user_id=admin.id,
                        email=admin.email,
                    )
                )

                for email, name, role in (MEMBER, VIEWER):
                    user = await session.scalar(select(User).where(User.email == email))
                    membership = None
                    if user is not None:
                        membership = await session.scalar(
                            select(TenantMembership).where(
                                TenantMembership.tenant_id == tenant.id,
                                TenantMembership.user_id == user.id,
                            )
                        )
                    if membership is None:
                        try:
                            await identity.invite_user(
                                admin_ctx, email=email, password=PASSWORD, role_name=role
                            )
                            print(f"Invited {name} as {role}")
                        except ConflictError:
                            print(f"{email} is already a member")
                        user = await session.scalar(select(User).where(User.email == email))
                    else:
                        print(f"{name} already in tenant")
                    if user is None:
                        raise SystemExit(f"Could not create {email}")
                    user.display_name = name
                    user.password_hash = hash_password(PASSWORD)
                    user.status = "active"
                await session.flush()
                print("Demo passwords reset for Daniel Okada, Priya Shah, and Samira Holt")
    finally:
        await dispose_engine()


def _login(client, email: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": PASSWORD, "tenant_slug": SLUG},
    )
    if response.status_code != 200:
        raise SystemExit(f"Login failed for {email}: {response.status_code} {response.text}")
    print(f"Login {email}: {response.status_code}")
    return response.json()["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _docs(client, token: str) -> list[dict]:
    response = client.get("/api/v1/documents", headers=_headers(token))
    if response.status_code != 200:
        raise SystemExit(f"Document list failed: {response.status_code} {response.text}")
    data = response.json()
    if isinstance(data, list):
        return data
    return data.get("items") or data.get("results") or []


def _titles(rows: list[dict]) -> set[str]:
    return {str(row.get("title") or "") for row in rows}


def _upload(client, token: str, filename: str, body: str, visibility: str) -> None:
    response = client.post(
        "/api/v1/documents",
        headers=_headers(token),
        data={"visibility": visibility, "allowed_roles": "[]"},
        files={"file": (filename, body.encode("utf-8"), "text/plain")},
    )
    if response.status_code != 200:
        raise SystemExit(f"Upload failed for {filename}: {response.status_code} {response.text}")
    payload = response.json()
    status = payload.get("status")
    if status not in {"completed", "unchanged"}:
        raise SystemExit(f"Upload of {filename} ended as {status}: {payload}")
    print(f"  {filename}: {status} ({visibility})")


def _conversations(client, token: str) -> list[dict]:
    response = client.get("/api/v1/conversations", headers=_headers(token))
    if response.status_code != 200:
        raise SystemExit(f"Conversation list failed: {response.status_code} {response.text}")
    data = response.json()
    if isinstance(data, list):
        return data
    return data.get("items") or []


def _has_question(rows: list[dict], question: str) -> bool:
    key = _title_key(question)
    return any(str(row.get("title") or "") == key for row in rows)


def _ask(client, token: str, question: str) -> dict:
    response = client.post(
        "/api/v1/chat",
        headers=_headers(token),
        json={"question": question},
    )
    if response.status_code != 200:
        raise SystemExit(f"Chat failed: {response.status_code} {response.text}")
    return response.json()


def _cited_names(payload: dict) -> list[str]:
    names = []
    for cite in payload.get("citations") or []:
        if isinstance(cite, dict) and cite.get("document_name"):
            names.append(str(cite["document_name"]))
    return names


def _ensure_ollama() -> None:
    import httpx

    try:
        probe = httpx.get("http://127.0.0.1:11434/api/tags", timeout=3)
        if probe.status_code == 200:
            print("Ollama is reachable")
            return
    except httpx.HTTPError:
        pass
    print("Ollama is not reachable. Starting `ollama serve` detached.")
    import subprocess

    subprocess.Popen(
        ["ollama", "serve"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(20):
        try:
            probe = httpx.get("http://127.0.0.1:11434/api/tags", timeout=2)
            if probe.status_code == 200:
                print("Ollama started")
                return
        except httpx.HTTPError:
            pass
        import time

        time.sleep(0.5)
    raise SystemExit("Ollama did not become reachable on http://127.0.0.1:11434")


def seed_content(*, skip_chat: bool) -> None:
    import httpx

    _ensure_ollama()
    with httpx.Client(base_url=API, timeout=300) as client:
        live = client.get("/api/v1/health/live")
        if live.status_code != 200:
            raise SystemExit(f"API is not live at {API} ({live.status_code}). Start it with ./scripts/start.sh")

        daniel = _login(client, ADMIN[0])
        priya = _login(client, MEMBER[0])
        samira = _login(client, VIEWER[0])

        print("Uploading documents")
        daniel_titles = _titles(_docs(client, daniel))
        if DOC_STANDARD not in daniel_titles:
            _upload(client, daniel, DOC_STANDARD, STANDARD_BODY, "tenant")
        else:
            print(f"  {DOC_STANDARD}: already visible to Daniel")

        priya_titles = _titles(_docs(client, priya))
        if DOC_PRIVATE not in priya_titles:
            _upload(client, priya, DOC_PRIVATE, PRIVATE_BODY, "private")
        else:
            print(f"  {DOC_PRIVATE}: already visible to Priya")

        daniel_titles = _titles(_docs(client, daniel))
        priya_titles = _titles(_docs(client, priya))
        samira_titles = _titles(_docs(client, samira))
        if DOC_STANDARD not in daniel_titles or DOC_STANDARD not in priya_titles or DOC_STANDARD not in samira_titles:
            raise SystemExit(f"{DOC_STANDARD} should be readable by Daniel, Priya, and Samira")
        if DOC_PRIVATE not in priya_titles:
            raise SystemExit("Priya should be able to read the private Helios Bank retrieval notes")
        if DOC_PRIVATE in daniel_titles or DOC_PRIVATE in samira_titles:
            raise SystemExit("Private Helios Bank retrieval notes leaked into Daniel or Samira's document list")
        print("ACL list check passed (Helios Bank notes are Priya-only)")

        if skip_chat:
            print("Skipping chat (--skip-chat)")
            return

        print("Asking seeded questions (live model)")
        _seed_question(
            client,
            priya,
            STANDARD_QUESTION,
            must_cite=DOC_STANDARD,
            must_contain=("northline-embed-v2",),
            must_not_contain=PRIVATE_LEAKS,
        )
        _seed_question(
            client,
            priya,
            PRIVATE_QUESTION,
            must_cite=DOC_PRIVATE,
            must_contain=("41.7", "helios"),
        )
        _seed_question(
            client,
            samira,
            STANDARD_QUESTION,
            must_cite=DOC_STANDARD,
            must_contain=("northline-embed-v2",),
            must_not_contain=PRIVATE_LEAKS,
        )
        _seed_question(
            client,
            samira,
            PRIVATE_QUESTION,
            must_not_cite=(DOC_PRIVATE,),
            must_not_contain=PRIVATE_LEAKS,
        )


def _seed_question(
    client,
    token: str,
    question: str,
    *,
    must_cite: str | None = None,
    must_not_cite: tuple[str, ...] = (),
    must_contain: tuple[str, ...] = (),
    must_not_contain: tuple[str, ...] = (),
) -> None:
    existing = _conversations(client, token)
    if _has_question(existing, question):
        print(f"  already answered: {question[:72]}")
        return
    print(f"  asking: {question[:72]}")
    payload = _ask(client, token, question)
    answer = str(payload.get("answer") or "")
    names = _cited_names(payload)
    print(f"    citations: {names or 'none'}")
    print(f"    answer: {answer[:280].replace(chr(10), ' ')}")
    lowered = answer.lower()
    for banned in must_not_cite:
        if any(banned.lower() in name.lower() for name in names):
            raise SystemExit(f"Citation leak ({banned}) for: {question}")
    if must_cite and not any(must_cite.lower() in name.lower() for name in names):
        raise SystemExit(f"Expected citation {must_cite} for: {question}\n{answer}")
    for needle in must_contain:
        if needle.lower() not in lowered:
            raise SystemExit(f"Answer missing {needle!r} for: {question}\n{answer}")
    for needle in must_not_contain:
        if needle.lower() in lowered:
            raise SystemExit(f"Answer leaked {needle!r} for: {question}\n{answer}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the Northline Software research demo")
    parser.add_argument("--skip-chat", action="store_true", help="Upload documents only")
    args = parser.parse_args()
    asyncio.run(ensure_people())
    seed_content(skip_chat=args.skip_chat)
    print()
    print("Northline Software demo is ready")
    print(f"  Tenant ID: {SLUG}")
    print(f"  Password:  {PASSWORD}")
    print(f"  MTS / Member:       {MEMBER[0]}  ({MEMBER[1]})")
    print(f"  SMTS / Tenant Admin: {ADMIN[0]}  ({ADMIN[1]})")
    print(f"  Viewer:             {VIEWER[0]}  ({VIEWER[1]})")
    print("  Open http://127.0.0.1:5173")


if __name__ == "__main__":
    main()
