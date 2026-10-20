"""`python -m app.worker`"""

from __future__ import annotations

import asyncio
import logging
import os

from prometheus_client import start_http_server

from app.config import get_settings
from app.db import make_engine, make_sessionmaker
from app.observability import setup_tracing
from app.providers import build_providers
from app.worker.runner import run_forever


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()
    setup_tracing(settings, "citesure-worker")
    # The worker is a separate process, so its counters (documents ingested, queue depth) need their own /metrics port.
    start_http_server(int(os.environ.get("WORKER_METRICS_PORT", "9100")))
    engine = make_engine(settings.database_url)
    try:
        await run_forever(make_sessionmaker(engine), build_providers(settings), settings)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
