"""公告分类 — 调用外部 argus_legal.AnnouncementClassifier(rollysys/announcement_filter)。

本模块只是薄包装:动态 import,缺失时给清晰的安装提示。

> 该依赖**不**写入 pyproject.toml,因为它当前未发布到 PyPI,需用户从源码装:
>     git clone https://github.com/rollysys/announcement_filter.git
>     cd announcement_filter && pip install -e .
"""

from __future__ import annotations

from functools import lru_cache

_INSTALL_HINT = (
    "announcement_filter not installed. Install with:\n"
    "    git clone https://github.com/rollysys/announcement_filter.git\n"
    "    cd announcement_filter && pip install -e ."
)


class ClassifierUnavailable(RuntimeError):
    """argus_legal 模块未装。"""


@lru_cache(maxsize=1)
def _get_classifier():
    try:
        from argus_legal import AnnouncementClassifier  # type: ignore[import-not-found]
    except ImportError as e:
        raise ClassifierUnavailable(_INSTALL_HINT) from e
    return AnnouncementClassifier()


def classify(title: str, ann_date: str | None = None) -> dict:
    """对单条公告 title 打标签,返回 {type, sub_type, legal_ref, ...}。

    ann_date: YYYYMMDD,可选(部分规则可能依赖时间)。
    """
    clf = _get_classifier()
    ann = {"title": title}
    if ann_date:
        ann["ann_date"] = ann_date
    return clf.classify(ann)


def is_available() -> bool:
    """检查 argus_legal 是否可用,不抛异常。"""
    try:
        _get_classifier()
        return True
    except ClassifierUnavailable:
        return False
