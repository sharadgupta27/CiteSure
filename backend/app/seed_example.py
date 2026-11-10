"""Sets up the fictional company in examples/: Fernhollow Bicycle Works (an invented bicycle maker).

    python -m app.seed_example                 # workspace, users, groups, collections; files come in through the inbox
    python -m app.seed_example --upload DIR    # ...and also upload the files in DIR/<collection>/ directly

The watched-folder inbox never creates workspaces or collections (docs/viewer-and-inbox.md), so this creates them with
the names of the folders in examples/inbox/fernhollow-bicycle-works/. Point the inbox at examples/inbox and every file is
imported into the collection named by its folder, with that collection's audience. Safe to re-run.

Logins (password from SEED_PASSWORD; default "citesure-demo" outside prod):
    admin@fernhollow.example     workspace admin: sees everything
    employee@fernhollow.example  member: Handbook only
    engineer@fernhollow.example  member of `engineering`: Handbook + Engineering
    finance@fernhollow.example   member of `finance`: Handbook + Finance-Confidential
"""

from __future__ import annotations

import argparse
import asyncio
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.db import make_engine, make_sessionmaker
from app.errors import Conflict
from app.providers import Providers, build_providers
from app.repositories import workspaces as workspaces_repo
from app.schemas import api as s
from app.seed import SUFFIXES, _get_or_create_user
from app.services.documents import DocumentService
from app.services.inbox import slugify
from app.services.ingest import ingest_document
from app.services.workspaces import WorkspaceService

WORKSPACE = "Fernhollow Bicycle Works"
DOMAIN = "fernhollow.example"
# user -> group (None: plain member). The admin is the workspace creator.
MEMBERS: dict[str, str | None] = {"employee": None, "engineer": "engineering", "finance": "finance"}
# collection -> group that may read it (None: the whole workspace). Folder names under examples/inbox/<workspace slug>/.
COLLECTIONS: dict[str, str | None] = {"Handbook": None, "Engineering": "engineering", "Finance-Confidential": "finance"}
INBOX_FOLDER = slugify(WORKSPACE)


@dataclass(frozen=True)
class ExampleResult:
    workspace_id: uuid.UUID
    collections: dict[str, uuid.UUID]
    uploaded: int


async def seed_example(
    sessionmaker: async_sessionmaker[AsyncSession],
    providers: Providers,
    settings: Settings,
    *,
    upload_dir: Path | None = None,
    password: str | None = None,
) -> ExampleResult:
    password = password or os.environ.get("SEED_PASSWORD") or ("" if settings.env == "prod" else "citesure-demo")
    if not password:
        raise RuntimeError("SEED_PASSWORD must be set to seed a production database (no default demo password in prod)")
    async with sessionmaker() as session:
        admin_id = await _get_or_create_user(session, f"admin@{DOMAIN}", password)
        member_ids = {name: await _get_or_create_user(session, f"{name}@{DOMAIN}", password) for name in MEMBERS}

        workspaces = WorkspaceService(session, providers.blobs)
        workspace = next((w for w in await workspaces.list_workspaces(admin_id) if w.name == WORKSPACE), None)
        if workspace is None:
            workspace = await workspaces.create_workspace(admin_id, WORKSPACE)
        for member_id in member_ids.values():
            if not await workspaces_repo.get_role(session, member_id, workspace.id):
                await workspaces_repo.add_membership(session, member_id, workspace.id, "member")
        await session.commit()

        groups = {g.name: g for g in await workspaces.list_groups(admin_id, workspace.id)}
        for name in sorted({g for g in MEMBERS.values() if g}):
            if name not in groups:
                groups[name] = await workspaces.create_group(admin_id, workspace.id, name)
        for user, group in MEMBERS.items():
            if group:
                await workspaces.add_group_member(admin_id, groups[group].id, f"{user}@{DOMAIN}")

        existing = {c.name: c for c in await workspaces.list_collections(admin_id, workspace.id)}
        collections: dict[str, uuid.UUID] = {}
        for name, group in COLLECTIONS.items():
            collection = existing.get(name) or await workspaces.create_collection(
                admin_id,
                workspace.id,
                s.CollectionCreate(
                    name=name,
                    visibility="groups" if group else "workspace",
                    group_ids=[groups[group].id] if group else [],
                ),
            )
            collections[name] = collection.id

        new_documents: list[uuid.UUID] = []
        if upload_dir is not None:
            docs = DocumentService(session, settings, providers.blobs)
            for name, collection_id in collections.items():
                for path in sorted((upload_dir / name).glob("*")):
                    if path.suffix.lower() not in SUFFIXES:
                        continue
                    try:
                        document = await docs.upload(admin_id, collection_id, path.name, path.read_bytes(), enqueue=False)
                        new_documents.append(document.id)
                    except Conflict:
                        pass  # already uploaded: safe to re-run

    # Inline, like app.seed: a worker elsewhere could claim queued jobs without having this process's files.
    for document_id in new_documents:
        async with sessionmaker() as session:
            await ingest_document(session, providers, settings, document_id)
    return ExampleResult(workspace.id, collections, len(new_documents))


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--upload", type=Path, metavar="DIR", help="also upload DIR/<collection>/* directly")
    args = parser.parse_args()
    settings = get_settings()
    engine = make_engine(settings.database_url)
    try:
        result = await seed_example(make_sessionmaker(engine), build_providers(settings), settings, upload_dir=args.upload)
    finally:
        await engine.dispose()
    print(f"Workspace '{WORKSPACE}' ({result.workspace_id}); collections: {', '.join(result.collections)}.")
    if args.upload:
        print(f"Uploaded {result.uploaded} new documents from {args.upload}.")
    else:
        print(f"Inbox folder for this workspace: <INBOX_ROOT>/{INBOX_FOLDER}/<collection>/")
    print(f"Log in as admin@, employee@, engineer@ or finance@{DOMAIN}.")


if __name__ == "__main__":
    asyncio.run(main())
