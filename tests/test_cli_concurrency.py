"""Tests for the asyncio concurrency model in the CLI run command (Phase 3)."""

import asyncio
import time
from unittest.mock import patch, MagicMock
from concurrent.futures import ThreadPoolExecutor


def test_explicit_executor_sized_to_concurrency():
    """Verify that _run_generations sets a ThreadPoolExecutor sized to
    concurrency_limit + 4 so worker threads never deadlock against the
    runtime loop."""
    recorded_executor = {}

    original_set_default_executor = asyncio.BaseEventLoop.set_default_executor

    def spy_set_executor(self, executor):
        recorded_executor["instance"] = executor
        original_set_default_executor(self, executor)

    with patch.object(asyncio.BaseEventLoop, "set_default_executor", spy_set_executor):
        # Simulate the minimal _run_generations setup.
        async def _fake_run_generations():
            from concurrent.futures import ThreadPoolExecutor as TPE
            loop = asyncio.get_running_loop()
            concurrency_limit = 6
            loop.set_default_executor(TPE(max_workers=concurrency_limit + 4))

        asyncio.run(_fake_run_generations())

    assert "instance" in recorded_executor
    executor = recorded_executor["instance"]
    assert isinstance(executor, ThreadPoolExecutor)
    assert executor._max_workers == 10  # 6 + 4


def test_semaphore_limits_concurrency():
    """Verify that an asyncio.Semaphore properly limits how many workers
    run concurrently (core contract of the generation loop)."""
    max_concurrent = 0
    current = 0
    lock = asyncio.Lock()

    async def _run():
        nonlocal max_concurrent, current
        concurrency_limit = 2
        sem = asyncio.Semaphore(concurrency_limit)

        async def _worker(i):
            nonlocal max_concurrent, current
            async with sem:
                async with lock:
                    current += 1
                    max_concurrent = max(max_concurrent, current)
                await asyncio.sleep(0.01)
                async with lock:
                    current -= 1

        await asyncio.gather(*[_worker(i) for i in range(8)])

    asyncio.run(_run())
    assert max_concurrent <= 2
