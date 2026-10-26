"""The summarize and compare agents. Both read only documents the caller may read (unreadable ids are a plain 404)
and return an ordinary, verified `Answer`: claims with citations, or a refusal."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.errors import InvalidInput
from app.models import Document
from app.providers import Providers
from app.rag.types import ScoredChunk
from app.repositories import asks as asks_repo
from app.repositories import learning_sources as sources_repo
from app.schemas import api as api_schemas
from app.schemas import learning as s
from app.services import acl
from app.services.ask import to_answer
from app.services.learning import access, grounded, layout, scoped


class AgentService:
    def __init__(self, session: AsyncSession, settings: Settings, providers: Providers) -> None:
        self.session = session
        self.settings = settings
        self.providers = providers

    async def summarize(self, user_id: uuid.UUID, workspace_id: uuid.UUID, body: s.SummarizeRequest) -> api_schemas.Answer:
        context = await acl.context_for_workspace(self.session, user_id, workspace_id)
        (document,) = await access.readable_documents(self.session, context, [body.document_id], require_ready=True)
        focus = (body.focus or "").strip()
        chunks, total = await self._summary_chunks(document, focus, context)
        notices = []
        if len({c.chunk_id for c in chunks}) < total:
            notices.append(
                f"This summary reads {len(chunks)} of {total} sections of the document"
                + (" that best match the focus." if focus else ", spread evenly across it.")
            )
        instruction = f'Summarize the document "{document.title}".' + (f" Focus on: {focus}" if focus else "")
        job = grounded.GroundedJob("summary", grounded.SUMMARY_PROMPT, instruction, focus)
        run = await grounded.generate(self.providers, self.settings, chunks, job)
        return await self._store(
            user_id,
            workspace_id,
            run,
            title=f"Summary: {document.title}",
            question=f"Summarize: {document.title}" + (f" (focus: {focus})" if focus else ""),
            task="summary",
            notices=notices,
        )

    async def compare(self, user_id: uuid.UUID, workspace_id: uuid.UUID, body: s.CompareRequest) -> api_schemas.Answer:
        context = await acl.context_for_workspace(self.session, user_id, workspace_id)
        documents = await access.readable_documents(self.session, context, body.document_ids, require_ready=True)
        if len(documents) < 2:
            raise InvalidInput("document_ids: choose at least two different documents")
        aspect = body.aspect.strip()
        vector = await self.providers.embedder.embed_query(aspect)
        chunks: list[ScoredChunk] = []
        for document in documents:
            found = await scoped.top_chunks_in_document(
                self.session,
                self.providers,
                self.settings,
                query=aspect,
                query_vector=vector,
                document_id=document.id,
                allowed_collection_ids=context.allowed_collection_ids,
                limit=self.settings.learning_compare_chunks_per_doc,
            )
            chunks.extend(sorted(found, key=lambda c: c.ord))
        job = grounded.GroundedJob(
            "compare", grounded.COMPARE_PROMPT, f"Compare the documents on this aspect: {aspect}", aspect
        )
        run = await grounded.generate(self.providers, self.settings, chunks, job)
        notices: list[str] = []
        if run.outcome.status == "answered":
            cited = {c.chunk.document_id for claim in run.outcome.claims for c in claim.citations}
            notices = [
                f'No supported statement on this aspect was found in "{d.title}".' for d in documents if d.id not in cited
            ]
        titles = ", ".join(d.title for d in documents)
        return await self._store(
            user_id,
            workspace_id,
            run,
            title=f"Compare: {aspect}",
            question=f"Compare {titles} on: {aspect}",
            task="compare",
            notices=notices,
        )

    async def _summary_chunks(
        self, document: Document, focus: str, context: acl.AccessContext
    ) -> tuple[list[ScoredChunk], int]:
        """The sections the summary model reads, in reading order, and how many sections the document has."""
        metas = (
            await sources_repo.chunk_meta(self.session, [document.id], allowed_collection_ids=context.allowed_collection_ids)
        ).get(document.id, [])
        limit = self.settings.learning_summary_chunks
        if focus:
            vector = await self.providers.embedder.embed_query(focus)
            ranked = await scoped.top_chunks_in_document(
                self.session,
                self.providers,
                self.settings,
                query=focus,
                query_vector=vector,
                document_id=document.id,
                allowed_collection_ids=context.allowed_collection_ids,
                limit=limit,
            )
            ids = [c.chunk_id for c in ranked]
        else:
            ids = [m.chunk_id for m in layout.spread(metas, limit)]
        chunks = await sources_repo.chunks_by_ids(self.session, ids, allowed_collection_ids=context.allowed_collection_ids)
        return chunks, len(metas)

    async def _store(
        self,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        run: grounded.GroundedRun,
        *,
        title: str,
        question: str,
        task: str,
        notices: list[str],
    ) -> api_schemas.Answer:
        thread = await asks_repo.create_thread(self.session, user_id, workspace_id, title)
        row = await grounded.store_run(
            self.session,
            self.settings,
            run,
            user_id=user_id,
            workspace_id=workspace_id,
            thread_id=thread.id,
            question=question,
            task=task,
            notices=notices,
        )
        await self.session.commit()
        return to_answer(row)
