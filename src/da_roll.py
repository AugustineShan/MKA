"""da_roll.py — 确定性滚动执行器 (Step 2 of /da skill).

消耗 da_schedule.yaml + da_facts + defaults.yaml.base_period,逐年产出 da_series:
  ppe_depreciation / fix_assets_net / cip_balance / ppe_capex / ppe_capex_split

口径锚点(spec §6.6):
  ppe_depreciation = 存量稳态折旧(scale 校准) + 扩张 cohort 折旧
  fix_assets_net   = 存量净值(base_net×(1+g)^t) + 扩张 cohort 累计净值
  cip_balance      = Σ各类 cip 余额(base cip 抽干 + 扩张 capex 堆积)
  ppe_capex        = 维持(=存量折旧) + 扩张 capex_by_cat + 有机;≠ 任何转固额(转固非现金)
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class DaAlignError(RuntimeError):
    """da_schedule 与 defaults.base_period / da_facts 不对齐时抛出。"""


# ---------------------------------------------------------------------------
# Task 2.1: da_schedule loader + base 对齐
# ---------------------------------------------------------------------------
def load_da_schedule(path: Path, defaults_base_period: str) -> dict | None:
    """加载 da_schedule.yaml,校验 base_year 与 defaults.base_period 一致。

    enabled=false 或文件不存在 → 返回 None(无 DA 覆盖,走 calc 默认)。
    base_year 不匹配 → DaAlignError(防止口径错位滚动)。
    """
    if not path.exists():
        return None
    sched = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not sched.get("enabled", False):
        return None
    base_year = sched.get("base_year")
    if str(base_year) != str(defaults_base_period)[:4]:
        raise DaAlignError(
            f"da_schedule.base_year={base_year} != defaults.base_period={defaults_base_period}")
    return sched


# ---------------------------------------------------------------------------
# Task 2.2: 存量永续更新折旧
# ---------------------------------------------------------------------------
def stock_depreciation(base_dep: float, g: float, t: int) -> float:
    """存量永续更新:折旧维持 base 水平 × (1+g)^t,不折尽。

    永续更新假设每年退役的资产被等额新购补上,故稳态折旧随存量规模 g 增长,
    不会像直线法那样折到 0。
    """
    return base_dep * (1.0 + g) ** t
