"""Ingestion worker. Development uses the in-process asyncio queue in the API."""

from __future__ import annotations

import asyncio
import signal
import sys

from app.adapters.db.session import dispose_engine, try_init_engine
from app.adapters.providers.queues.asyncio_queue import set_job_handler
from app.application.jobs import run_ingestion_job
from app.application.providers import load_providers
from app.config.load import load_platform_settings
from app.core.logging import configure_logging


async def _run() -> int:
    load_providers()
    settings = load_platform_settings(resolve=False)
    configure_logging(settings.observability.log_level)
    try_init_engine(settings)

    async def _handler(job_id, job_type, payload, ctx):
        await run_ingestion_job(job_id, settings, ctx)

    set_job_handler(_handler)
    print(
        f"rag-platform worker queue={settings.queue.provider} env={settings.platform.environment}",
        file=sys.stderr,
        flush=True,
    )
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    await dispose_engine()
    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
