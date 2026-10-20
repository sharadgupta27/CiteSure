"""Background worker: polls the jobs table. Ingestion, reindexing and evaluation runs happen here, never in a
request handler (a 200-page PDF must not block an HTTP worker)."""

from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.observability import QUEUE_DEPTH
from app.providers import Providers
from app.repositories import jobs as jobs_repo
from app.services.documents import INGEST_JOB
from app.services.eval_runner import execute_eval_run
from app.services.evaluation import EVAL_JOB
from app.services.ingest import ingest_document

log = logging.getLogger("citesure.worker")
POLL_SECONDS = 1.0


async def _dispatch(session: AsyncSession, providers: Providers, settings: Settings, job: jobs_repo.ClaimedJob) -> None:
    if job.kind == INGEST_JOB:
        await ingest_document(session, providers, settings, uuid.UUID(job.payload["document_id"]))
    elif job.kind == EVAL_JOB:
        await execute_eval_run(session, providers, settings, uuid.UUID(job.payload["run_id"]))
    else:
        raise ValueError(f"Unknown job kind: {job.kind}")


async def process_one(sessionmaker: async_sessionmaker[AsyncSession], providers: Providers, settings: Settings) -> bool:
    """Claim and run one job. Returns False when the queue is empty."""
    async with sessionmaker() as session:
        job = await jobs_repo.claim_next(session)
        await session.commit()
        QUEUE_DEPTH.set(await jobs_repo.queue_depth(session))
    if job is None:
        return False
    log.info("job started id=%s kind=%s attempt=%s", job.id, job.kind, job.attempts)
    try:
        async with sessionmaker() as session:
            await _dispatch(session, providers, settings, job)
        async with sessionmaker() as session:
            await jobs_repo.mark_done(session, job.id)
            await session.commit()
    except Exception as exc:
        log.warning("job failed id=%s kind=%s error=%s", job.id, job.kind, type(exc).__name__)
        async with sessionmaker() as session:
            await jobs_repo.mark_failed(session, job, f"{type(exc).__name__}: {exc}")
            await session.commit()
    return True


async def drain(sessionmaker: async_sessionmaker[AsyncSession], providers: Providers, settings: Settings) -> int:
    """Run jobs until none is due. Used by tests, the seed script and the eval CLI."""
    done = 0
    while await process_one(sessionmaker, providers, settings):
        done += 1
    return done


async def run_forever(sessionmaker: async_sessionmaker[AsyncSession], providers: Providers, settings: Settings) -> None:
    log.info("worker started")
    while True:
        if not await process_one(sessionmaker, providers, settings):
            await asyncio.sleep(POLL_SECONDS)
