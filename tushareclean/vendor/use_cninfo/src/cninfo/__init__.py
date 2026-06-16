"""cninfo-cli — on-demand fetcher for A-share announcements from cninfo.com.cn."""

__version__ = "0.1.0"

from cninfo.api import (
    CATEGORY_BNDBG,
    CATEGORY_NDBG,
    CATEGORY_SJDBG,
    CATEGORY_YJDBG,
    adjunct_to_url,
    clean_title,
    epoch_ms_to_ann_date,
    query_all,
    query_page,
)

__all__ = [
    "CATEGORY_BNDBG",
    "CATEGORY_NDBG",
    "CATEGORY_SJDBG",
    "CATEGORY_YJDBG",
    "adjunct_to_url",
    "clean_title",
    "epoch_ms_to_ann_date",
    "query_all",
    "query_page",
]
