"""orgid 模块测试 — mock cninfo topSearch。"""

import json
from unittest.mock import MagicMock

import pytest

from cninfo import orgid


def _mock_response(payload, status=200):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload
    r.raise_for_status.return_value = None
    return r


def test_get_orgid_cache_hit(tmp_cache_dir):
    from cninfo.cache import upsert_orgid

    upsert_orgid("600519", "gssh0600519")
    assert orgid.get_orgid("600519") == "gssh0600519"


def test_lookup_orgid_writes_cache(tmp_cache_dir, sample_topsearch_response, monkeypatch):
    fake_session = MagicMock()
    fake_session.post.return_value = _mock_response(sample_topsearch_response)

    org = orgid.lookup_orgid("600519", session=fake_session)
    assert org == "gssh0600519"

    # cache 写入
    cached = json.loads((tmp_cache_dir / "orgid_map.json").read_text())
    assert cached == {"600519": "gssh0600519"}

    # post 调用参数检查
    args, kwargs = fake_session.post.call_args
    assert args[0] == orgid.TOPSEARCH_URL
    assert kwargs["data"] == {"keyWord": "600519", "maxNum": "10"}


def test_lookup_orgid_not_found(tmp_cache_dir):
    fake_session = MagicMock()
    fake_session.post.return_value = _mock_response([])
    with pytest.raises(orgid.OrgIdNotFound):
        orgid.lookup_orgid("000000", session=fake_session)


def test_lookup_orgid_filters_by_code(tmp_cache_dir):
    fake_session = MagicMock()
    fake_session.post.return_value = _mock_response(
        [{"code": "600518", "orgId": "x"}, {"code": "600519", "orgId": "gssh0600519"}]
    )
    assert orgid.lookup_orgid("600519", session=fake_session) == "gssh0600519"


def test_get_orgid_cache_only_raises(tmp_cache_dir):
    with pytest.raises(orgid.OrgIdNotFound):
        orgid.get_orgid("999999", fetch_if_missing=False)
