"""共享 fixture。"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def sample_query_response() -> dict:
    return json.loads((FIXTURES / "cninfo_query_sample.json").read_text(encoding="utf-8"))


@pytest.fixture
def sample_topsearch_response() -> list:
    return json.loads((FIXTURES / "topsearch_600519.json").read_text(encoding="utf-8"))


@pytest.fixture
def sample_pdf_bytes() -> bytes:
    return (FIXTURES / "sample.pdf").read_bytes()


@pytest.fixture
def tmp_cache_dir(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("CNINFO_CACHE_DIR", str(tmp_path))
    yield tmp_path


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    """单元测试默认禁止真实网络。需要真实网络的测试用 @pytest.mark.network 跳过本 fixture。"""
    if os.environ.get("CNINFO_ALLOW_NETWORK") == "1":
        return
    import requests

    def _block(*a, **kw):
        raise RuntimeError(
            "real network blocked in tests. Set CNINFO_ALLOW_NETWORK=1 to allow, "
            "or monkeypatch requests.{get,post} in your test."
        )

    monkeypatch.setattr(requests, "get", _block)
    monkeypatch.setattr(requests, "post", _block)
