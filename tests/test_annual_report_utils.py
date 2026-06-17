"""Tests for shared annual-report helpers, focused on the concurrency utility."""

import threading
import time

import pytest

from src import annual_report_utils as aru


def test_parallel_map_preserves_input_order_regardless_of_completion():
    """result[i] must correspond to items[i] even when later items finish first."""

    def work(n):
        # Earlier items sleep longer, so completion order reverses input order.
        time.sleep(0.05 * (5 - n))
        return n * 10

    out = aru.parallel_map(work, [1, 2, 3, 4], max_workers=4)
    assert out == [10, 20, 30, 40]


def test_parallel_map_runs_concurrently():
    """With enough workers, total wall-clock is ~max(task), not sum(task)."""
    barrier = threading.Barrier(4, timeout=5)

    def work(_):
        # If tasks ran serially this barrier would never trip and raise.
        barrier.wait()
        return True

    out = aru.parallel_map(work, list(range(4)), max_workers=4)
    assert out == [True, True, True, True]


def test_parallel_map_propagates_exceptions():
    def work(n):
        if n == 2:
            raise ValueError("boom")
        return n

    with pytest.raises(ValueError, match="boom"):
        aru.parallel_map(work, [1, 2, 3], max_workers=3)


def test_parallel_map_empty_returns_empty():
    assert aru.parallel_map(lambda x: x, []) == []


def test_parallel_map_single_worker_runs_inline():
    calls: list[int] = []

    def work(n):
        calls.append(n)
        return n

    out = aru.parallel_map(work, [3, 1, 2], max_workers=1)
    assert out == [3, 1, 2]
    assert calls == [3, 1, 2]  # serial, in order


def test_llm_max_workers_defaults_and_env(monkeypatch):
    monkeypatch.delenv("LLM_MAX_WORKERS", raising=False)
    assert aru.llm_max_workers() == 6
    monkeypatch.setenv("LLM_MAX_WORKERS", "3")
    assert aru.llm_max_workers() == 3
    monkeypatch.setenv("LLM_MAX_WORKERS", "garbage")
    assert aru.llm_max_workers() == 6  # invalid falls back to default
