"""classify 薄包装测试 — 不真实依赖 argus_legal。"""

import sys

import pytest

from cninfo import classify as classify_mod


def test_classify_unavailable_when_argus_missing(monkeypatch):
    classify_mod._get_classifier.cache_clear()
    monkeypatch.setitem(sys.modules, "argus_legal", None)  # 模拟 import 失败
    assert classify_mod.is_available() is False
    classify_mod._get_classifier.cache_clear()
    monkeypatch.setitem(sys.modules, "argus_legal", None)
    with pytest.raises(classify_mod.ClassifierUnavailable):
        classify_mod.classify("控股股东减持股份计划公告")


def test_classify_calls_argus(monkeypatch):
    classify_mod._get_classifier.cache_clear()

    class FakeClassifier:
        def classify(self, ann):
            return {
                "type": "shareholder",
                "sub_type": "reduce_plan",
                "legal_ref": "csrc-disclosure_mgmt-order-224",
                "title": ann["title"],
            }

    fake_module = type(sys)("argus_legal")
    fake_module.AnnouncementClassifier = lambda: FakeClassifier()
    monkeypatch.setitem(sys.modules, "argus_legal", fake_module)

    res = classify_mod.classify("控股股东减持股份计划公告", "20260411")
    assert res["type"] == "shareholder"
    assert res["sub_type"] == "reduce_plan"
    classify_mod._get_classifier.cache_clear()
