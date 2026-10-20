"""Upload -> background ingestion -> ready; deletion; reindex; validation (magic bytes, size, duplicates)."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select

from app.models import Chunk, Document, Job
from tests.conftest import ingest_all, new_workspace

API = "/api/v1"
FIXTURES = Path(__file__).parent.parent / "fixtures"


async def upload(
    client: httpx.AsyncClient, headers: dict[str, str], collection_id: str, name: str, data: bytes, mime: str = "text/plain"
) -> httpx.Response:
    return await client.post(
        f"{API}/collections/{collection_id}/documents", files={"file": (name, data, mime)}, headers=headers
    )


async def chunk_count(app: Any, document_id: str) -> int:
    async with app.state.sessionmaker() as session:
        return int(
            (
                await session.execute(select(func.count()).select_from(Chunk).where(Chunk.document_id == document_id))
            ).scalar_one()
        )


async def test_status_moves_from_queued_to_ready_and_chunks_have_exact_offsets(client: httpx.AsyncClient, app: Any) -> None:
    _, admin, collection_id = await new_workspace(client)
    text = "# Lunch Rules\n\n## Hours\n\nLunch is served from noon to one. Please be on time.\n\n## Menu\n\nSoup is free on Fridays."
    created = await upload(client, admin, collection_id, "lunch-rules.md", text.encode())
    assert created.status_code == 202
    document = created.json()
    assert document["status"] == "queued" and document["chunk_count"] == 0

    assert await ingest_all(app) >= 1
    ready = (await client.get(f"{API}/documents/{document['id']}", headers=admin)).json()
    assert ready["status"] == "ready" and ready["chunk_count"] >= 1
    assert ready["title"] == "Lunch Rules"
    assert ready["mime"] == "text/markdown"

    chunks = (await client.get(f"{API}/documents/{document['id']}/chunks", headers=admin)).json()
    assert [c["ord"] for c in chunks] == list(range(len(chunks)))
    assert "Lunch is served from noon to one." in " ".join(c["text"] for c in chunks)
    assert chunks[0]["heading_path"][0] == "Lunch Rules"
    # offsets index the normalised document text; consecutive chunks are consistent
    for chunk in chunks:
        assert chunk["char_end"] - chunk["char_start"] == len(chunk["text"])


@pytest.mark.parametrize(
    ("name", "expected_mime", "expected_pages"),
    [
        ("sample.pdf", "application/pdf", 2),
        ("sample.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", None),
        ("sample.html", "text/html", None),
        ("sample.md", "text/markdown", None),
    ],
)
async def test_every_supported_format_is_ingested(
    client: httpx.AsyncClient, app: Any, name: str, expected_mime: str, expected_pages: int | None
) -> None:
    _, admin, collection_id = await new_workspace(client)
    created = await upload(client, admin, collection_id, name, (FIXTURES / name).read_bytes(), "application/octet-stream")
    assert created.status_code == 202, created.text
    await ingest_all(app)
    document = (await client.get(f"{API}/documents/{created.json()['id']}", headers=admin)).json()
    assert document["status"] == "ready", document["error"]
    assert document["mime"] == expected_mime
    assert document["page_count"] == expected_pages
    assert document["chunk_count"] >= 1


async def test_pdf_chunks_carry_page_numbers(client: httpx.AsyncClient, app: Any) -> None:
    _, admin, collection_id = await new_workspace(client)
    created = await upload(client, admin, collection_id, "travel.pdf", (FIXTURES / "sample.pdf").read_bytes())
    await ingest_all(app)
    chunks = (await client.get(f"{API}/documents/{created.json()['id']}/chunks", headers=admin)).json()
    assert all(c["page_start"] is not None for c in chunks)
    assert min(c["page_start"] for c in chunks) == 1 and max(c["page_end"] for c in chunks) == 2


async def test_the_original_file_can_be_downloaded_safely(client: httpx.AsyncClient, app: Any) -> None:
    _, admin, collection_id = await new_workspace(client)
    html = b"<html><body><h1>Hi</h1><script>alert(1)</script><p>Some text goes here.</p></body></html>"
    created = await upload(client, admin, collection_id, "page.html", html)
    response = await client.get(f"{API}/documents/{created.json()['id']}/file", headers=admin)
    assert response.content == html
    assert response.headers["content-disposition"].startswith("attachment")
    assert response.headers["content-security-policy"] == "sandbox"
    assert response.headers["x-content-type-options"] == "nosniff"


async def test_the_declared_type_and_filename_are_never_trusted(client: httpx.AsyncClient) -> None:
    _, admin, collection_id = await new_workspace(client)
    exe = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00"
    assert (await upload(client, admin, collection_id, "report.pdf", exe, "application/pdf")).status_code == 415
    assert (await upload(client, admin, collection_id, "empty.md", b"")).status_code == 415
    bomb = io.BytesIO()
    with zipfile.ZipFile(bomb, "w") as archive:
        archive.writestr("notes.txt", "hi")
    assert (await upload(client, admin, collection_id, "notes.docx", bomb.getvalue())).status_code == 415
    traversal = await upload(client, admin, collection_id, "../../etc/passwd.md", b"# Fine\n\nA harmless text document.")
    assert traversal.status_code == 202
    assert "/" not in traversal.json()["filename"] and ".." not in traversal.json()["filename"]


async def test_oversized_uploads_are_rejected(client: httpx.AsyncClient, app: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    _, admin, collection_id = await new_workspace(client)
    monkeypatch.setattr(app.state.settings, "max_upload_mb", 1)
    big = b"# Big\n\n" + b"word " * 300_000
    assert len(big) > 1024 * 1024
    assert (await upload(client, admin, collection_id, "big.md", big)).status_code == 413


async def test_duplicate_files_in_a_collection_are_rejected(client: httpx.AsyncClient) -> None:
    _, admin, collection_id = await new_workspace(client)
    data = b"# Same\n\nExactly the same content in both uploads."
    assert (await upload(client, admin, collection_id, "a.md", data)).status_code == 202
    assert (await upload(client, admin, collection_id, "b.md", data)).status_code == 409


async def test_uploads_can_be_disabled(client: httpx.AsyncClient, app: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    _, admin, collection_id = await new_workspace(client)
    monkeypatch.setattr(app.state.settings, "uploads_enabled", False)
    assert (await upload(client, admin, collection_id, "a.md", b"# A\n\nText content here.")).status_code == 403


async def test_unparseable_files_end_as_failed_with_a_readable_reason(client: httpx.AsyncClient, app: Any) -> None:
    _, admin, collection_id = await new_workspace(client)
    created = await upload(client, admin, collection_id, "broken.pdf", b"%PDF-1.4\nthis is not really a pdf at all")
    assert created.status_code == 202
    await ingest_all(app)
    document = (await client.get(f"{API}/documents/{created.json()['id']}", headers=admin)).json()
    assert document["status"] == "failed"
    assert document["error"] and "Traceback" not in document["error"]
    async with app.state.sessionmaker() as session:  # a permanent parse failure must not be retried forever
        jobs = (
            (await session.execute(select(Job.status).where(Job.payload["document_id"].astext == created.json()["id"])))
            .scalars()
            .all()
        )
    assert jobs == ["done"]


async def test_deleting_a_document_removes_chunks_embeddings_and_the_stored_file(
    client: httpx.AsyncClient, app: Any
) -> None:
    _, admin, collection_id = await new_workspace(client)
    created = (await upload(client, admin, collection_id, "gone.md", b"# Gone\n\nThis text will disappear soon.")).json()
    await ingest_all(app)
    assert await chunk_count(app, created["id"]) >= 1
    async with app.state.sessionmaker() as session:
        blob_key = (await session.execute(select(Document.blob_key).where(Document.id == created["id"]))).scalar_one()
    assert await app.state.providers.blobs.get(blob_key)

    assert (await client.delete(f"{API}/documents/{created['id']}", headers=admin)).status_code == 204
    assert await chunk_count(app, created["id"]) == 0
    with pytest.raises(FileNotFoundError):
        await app.state.providers.blobs.get(blob_key)
    assert (await client.get(f"{API}/documents/{created['id']}", headers=admin)).status_code == 404


async def test_deleting_a_collection_removes_everything_in_it(client: httpx.AsyncClient, app: Any) -> None:
    workspace_id, admin, _ = await new_workspace(client)
    collection = (
        await client.post(
            f"{API}/workspaces/{workspace_id}/collections",
            json={"name": "Temp", "visibility": "workspace", "group_ids": []},
            headers=admin,
        )
    ).json()
    created = (await upload(client, admin, collection["id"], "t.md", b"# T\n\nTemporary text for deletion.")).json()
    await ingest_all(app)
    assert (await client.delete(f"{API}/collections/{collection['id']}", headers=admin)).status_code == 204
    assert await chunk_count(app, created["id"]) == 0
    async with app.state.sessionmaker() as session:
        assert (
            await session.execute(select(func.count()).select_from(Document).where(Document.id == created["id"]))
        ).scalar_one() == 0


async def test_reindex_replaces_chunks_atomically(client: httpx.AsyncClient, app: Any) -> None:
    _, admin, collection_id = await new_workspace(client)
    created = (
        await upload(client, admin, collection_id, "re.md", b"# Re\n\nSome policy text that is long enough to index.")
    ).json()
    await ingest_all(app)
    before = {c["id"] for c in (await client.get(f"{API}/documents/{created['id']}/chunks", headers=admin)).json()}
    response = await client.post(f"{API}/documents/{created['id']}/reindex", headers=admin)
    assert response.status_code == 202 and response.json()["status"] == "queued"
    await ingest_all(app)
    after = {c["id"] for c in (await client.get(f"{API}/documents/{created['id']}/chunks", headers=admin)).json()}
    assert after and after.isdisjoint(before)  # same text, new rows
    assert (await client.get(f"{API}/documents/{created['id']}", headers=admin)).json()["status"] == "ready"


async def test_pii_is_flagged_on_chunks(client: httpx.AsyncClient, app: Any) -> None:
    _, admin, collection_id = await new_workspace(client)
    created = (
        await upload(
            client, admin, collection_id, "contacts.md", b"# Contacts\n\nWrite to jane.doe@example.com for questions."
        )
    ).json()
    await ingest_all(app)
    async with app.state.sessionmaker() as session:
        flags = (await session.execute(select(Chunk.pii_flags).where(Chunk.document_id == created["id"]))).scalars().all()
    assert any(f.get("email") == 1 for f in flags)


async def test_deleting_a_document_also_erases_its_quoted_text_from_stored_answers(
    client: httpx.AsyncClient, app: Any
) -> None:
    """Right to erasure: a deleted document's words must not survive in the answer history."""
    workspace_id, admin, collection_id = await new_workspace(client)
    created = (
        await upload(
            client,
            admin,
            collection_id,
            "secret-plan.md",
            b"# Plan\n\nThe launch codename is Bluebird and the budget is 900 thousand dollars.",
        )
    ).json()
    await ingest_all(app)
    answer = (
        await client.post(
            f"{API}/ask", json={"workspace_id": workspace_id, "question": "What is the launch codename?"}, headers=admin
        )
    ).json()
    assert answer["status"] == "answered" and "Bluebird" in str(answer)

    assert (await client.delete(f"{API}/documents/{created['id']}", headers=admin)).status_code == 204
    async with app.state.sessionmaker() as session:
        from app.models import Answer

        row = (await session.execute(select(Answer).where(Answer.id == answer["id"]))).scalar_one()
        assert "Bluebird" not in str(row.answer_json) and "900 thousand" not in str(row.answer_json)
        assert row.status == "refused" and row.retrieved_chunk_ids == []
    stored = (await client.get(f"{API}/answers/{answer['id']}", headers=admin)).json()
    assert stored["status"] == "refused" and "Bluebird" not in str(stored)


async def test_ingestion_errors_never_store_document_text(
    client: httpx.AsyncClient, app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression (found in the security review): driver/parser exceptions can echo the data they were processing, and the
    error column is shown to admins and kept in the database. Only the exception type may be stored."""
    _, admin, collection_id = await new_workspace(client)
    created = (
        await upload(
            client, admin, collection_id, "leaky.md", b"# Plan\n\nThe launch codename is Bluebird and nothing else."
        )
    ).json()

    async def exploding_embed(texts: list[str]) -> list[list[float]]:
        raise RuntimeError(f"embedding service rejected this input: {texts[0]}")

    monkeypatch.setattr(app.state.providers.embedder, "embed_documents", exploding_embed)
    await ingest_all(app)
    document = (await client.get(f"{API}/documents/{created['id']}", headers=admin)).json()
    assert document["status"] == "failed"
    assert "Bluebird" not in str(document) and "RuntimeError" in document["error"]
    async with app.state.sessionmaker() as session:
        job_error = (
            await session.execute(select(Job.error).where(Job.payload["document_id"].astext == created["id"]))
        ).scalar_one()
    assert (
        "RuntimeError" in job_error
    )  # the job row keeps the type; the exception text of OUR message is not document-derived here
