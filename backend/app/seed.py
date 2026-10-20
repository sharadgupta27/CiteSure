"""Loads the demo company: users, a workspace, two collections (one HR-only), the corpus and the golden set.

    python -m app.seed

Demo logins (password from SEED_PASSWORD, default "citesure-demo" for local development only):
    admin@acme.example     workspace admin
    employee@acme.example  plain member: cannot see People-Ops-Confidential
    hr@acme.example        member of the `hr` group: can see it
    agent@acme.example     plain member: the scoped service user for the MCP server (same access as `employee`)
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.db import make_engine, make_sessionmaker
from app.errors import Conflict
from app.providers import Providers, build_providers
from app.repositories import evals as evals_repo
from app.repositories import users as users_repo
from app.repositories import workspaces as workspaces_repo
from app.schemas import api as s
from app.security import hash_password
from app.services.documents import DocumentService
from app.services.ingest import ingest_document
from app.services.workspaces import WorkspaceService

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS_DIR = Path(os.environ.get("CORPUS_DIR", REPO_ROOT / "corpus" / "demo"))
GOLDEN_FILE = Path(os.environ.get("GOLDEN_FILE", REPO_ROOT / "backend" / "evals" / "golden.jsonl"))
DOMAIN = "acme.example"
SUFFIXES = {".md", ".html", ".pdf", ".docx"}


@dataclass(frozen=True)
class SeedResult:
    workspace_id: uuid.UUID
    admin_id: uuid.UUID
    general_id: uuid.UUID
    confidential_id: uuid.UUID
    documents: int


async def _get_or_create_user(session: AsyncSession, email: str, password: str) -> uuid.UUID:
    user = await users_repo.get_by_email(session, email)
    if user is None:
        user = await users_repo.create_user(session, email, await hash_password(password))
        await session.commit()
    return user.id


async def seed_demo(
    sessionmaker: async_sessionmaker[AsyncSession],
    providers: Providers,
    settings: Settings,
    *,
    workspace_name: str = "Acme Robotics",
    load_golden: bool = True,
    password: str | None = None,
) -> SeedResult:
    password = password or os.environ.get("SEED_PASSWORD") or ("" if settings.env == "prod" else "citesure-demo")
    if not password:
        raise RuntimeError("SEED_PASSWORD must be set to seed a production database (no default demo password in prod)")
    async with sessionmaker() as session:
        admin_id = await _get_or_create_user(session, f"admin@{DOMAIN}", password)
        employee_id = await _get_or_create_user(session, f"employee@{DOMAIN}", password)
        hr_id = await _get_or_create_user(session, f"hr@{DOMAIN}", password)
        agent_id = await _get_or_create_user(session, f"agent@{DOMAIN}", os.environ.get("AGENT_PASSWORD") or password)

        workspaces = WorkspaceService(session, providers.blobs)
        workspace = next((w for w in await workspaces.list_workspaces(admin_id) if w.name == workspace_name), None)
        if workspace is None:
            workspace = await workspaces.create_workspace(admin_id, workspace_name)
        for member_id, role in ((employee_id, "member"), (hr_id, "member"), (agent_id, "member")):
            if not await workspaces_repo.get_role(session, member_id, workspace.id):
                await workspaces_repo.add_membership(session, member_id, workspace.id, role)
        await session.commit()

        groups = {g.name: g for g in await workspaces.list_groups(admin_id, workspace.id)}
        hr_group = groups.get("hr") or await workspaces.create_group(admin_id, workspace.id, "hr")
        await workspaces.add_group_member(admin_id, hr_group.id, f"hr@{DOMAIN}")

        existing = {c.name: c for c in await workspaces.list_collections(admin_id, workspace.id)}
        general = existing.get("General") or await workspaces.create_collection(
            admin_id, workspace.id, s.CollectionCreate(name="General", visibility="workspace", group_ids=[])
        )
        confidential = existing.get("People-Ops-Confidential") or await workspaces.create_collection(
            admin_id,
            workspace.id,
            s.CollectionCreate(name="People-Ops-Confidential", visibility="groups", group_ids=[hr_group.id]),
        )

        docs = DocumentService(session, settings, providers.blobs)
        uploaded = 0
        new_documents: list[uuid.UUID] = []
        for folder, collection in (("general", general), ("people-ops-confidential", confidential)):
            for path in sorted((CORPUS_DIR / folder).glob("*")):
                if path.suffix.lower() not in SUFFIXES:
                    continue
                try:
                    document = await docs.upload(admin_id, collection.id, path.name, path.read_bytes(), enqueue=False)
                    new_documents.append(document.id)
                    uploaded += 1
                except Conflict:
                    pass  # already loaded: the seed is safe to re-run

        if load_golden and GOLDEN_FILE.exists():
            known = {g.question for g in await evals_repo.list_golden(session, workspace.id)}
            for line in GOLDEN_FILE.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                item = json.loads(line)
                if item["question"] in known:
                    continue
                await evals_repo.create_golden(
                    session,
                    workspace_id=workspace.id,
                    question=item["question"],
                    expected_answer=item["expected_answer"],
                    expected_quotes=item["expected_quotes"],
                    answerable=item["answerable"],
                    ask_as=item["ask_as"],
                    source="manual",
                    tags=item["tags"],
                    reason=item["reason"],
                )
            await session.commit()

    # Ingest inline instead of through the shared job queue: a worker running elsewhere (for example the Compose
    # container) could claim the jobs but would not have this process's files.
    started = time.perf_counter()
    for document_id in new_documents:
        async with sessionmaker() as session:
            await ingest_document(session, providers, settings, document_id)
    elapsed = time.perf_counter() - started
    if new_documents:
        per_minute = len(new_documents) / max(elapsed, 0.001) * 60
        embedder = settings.embedding_provider
        print(f"Ingested {len(new_documents)} documents in {elapsed:.1f}s ({per_minute:.0f}/min, embedder={embedder})")
    return SeedResult(workspace.id, admin_id, general.id, confidential.id, uploaded)


async def main() -> None:
    settings = get_settings()
    engine = make_engine(settings.database_url)
    try:
        result = await seed_demo(make_sessionmaker(engine), build_providers(settings), settings)
    finally:
        await engine.dispose()
    print(f"Seeded workspace {result.workspace_id}: {result.documents} new documents.")
    print(f"Log in as admin@{DOMAIN}, employee@{DOMAIN} or hr@{DOMAIN}. The MCP server uses agent@{DOMAIN}.")


if __name__ == "__main__":
    asyncio.run(main())
