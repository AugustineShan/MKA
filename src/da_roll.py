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


# ---------------------------------------------------------------------------
# Task 2.3: 扩张 Cohort 直线折旧
# ---------------------------------------------------------------------------
@dataclass
class Cohort:
    """扩张转固形成的资产 cohort:直线折旧,折尽停计,净值不低于残值。

    start_year = 转固年份(当年开始计提);life 年后折尽,残值 = gross*salvage_rate。
    """
    gross: float
    salvage_rate: float
    life: int
    start_year: int

    def annual_dep(self) -> float:
        """年折旧额 =(原值 - 残值)/ 寿命,直线法。"""
        return self.gross * (1.0 - self.salvage_rate) / self.life

    def dep_in_year(self, year: int) -> float:
        """某年折旧:转固前 0,life 年内 = annual_dep,折尽后 0。"""
        if year < self.start_year:
            return 0.0
        elapsed = year - self.start_year
        if elapsed >= self.life:
            return 0.0
        return self.annual_dep()

    def net_in_year(self, year: int) -> float:
        """某年净值:转固前 0,否则 max(原值 - 累计折旧, 残值)。"""
        if year < self.start_year:
            return 0.0
        elapsed = min(year - self.start_year, self.life)
        depreciated = self.annual_dep() * elapsed
        salvage = self.gross * self.salvage_rate
        return max(self.gross - depreciated, salvage)


# ---------------------------------------------------------------------------
# Task 2.4: base_cip_to_fixed 转固 + CipState
# ---------------------------------------------------------------------------
class CipInvariantError(RuntimeError):
    """cip 余额违反非负 / base 转固超额不变量时抛出。"""


@dataclass
class CipState:
    """某类资产的在建工程(CIP)滚动状态。

    cip_balance(year) = base_cip + Σ扩张capex - Σbase转固 - Σ扩张转固
    transferred_cohorts(year) = 当年转固额(base+expansion 合并)形成的 Cohort 列表
    """
    base_cip: float
    base_transfers: dict
    expansion_capex: dict
    expansion_transfers: dict
    life: int
    salvage: float
    start_year: int

    def cip_balance(self, year: int) -> float:
        bal = self.base_cip
        for y in range(self.start_year, year + 1):
            bal += self.expansion_capex.get(y, 0.0)
            bal -= self.base_transfers.get(y, 0.0)
            bal -= self.expansion_transfers.get(y, 0.0)
        if bal < -1e-6:
            raise CipInvariantError(f"cip negative at {year}: {bal}")
        return bal

    def transferred_cohorts(self, year: int) -> list[Cohort]:
        out: list[Cohort] = []
        amt = self.base_transfers.get(year, 0.0) + self.expansion_transfers.get(year, 0.0)
        if amt > 0:
            out.append(Cohort(amt, self.salvage, self.life, year))
        return out


def roll_cip(base_cip: float, base_cip_to_fixed: dict,
             expansion_capex_by_year: dict, expansion_cip_to_fixed: dict,
             cat_life: int, cat_salvage: float, start_year: int) -> CipState:
    """校验 base 转固不超额并构造 CipState。

    base cip 是存量(期初余额),其累计转固不得超过 base_cip;扩张 capex 是流量,
    当年堆积可被当年或后续转固消耗。两类转固合并形成 cohort。
    """
    cum_base = sum(base_cip_to_fixed.values())
    if cum_base > base_cip + 1e-6:
        raise CipInvariantError(f"base cip over-transferred: {cum_base} > {base_cip}")
    return CipState(base_cip, base_cip_to_fixed, expansion_capex_by_year,
                    expansion_cip_to_fixed, cat_life, cat_salvage, start_year)


# ---------------------------------------------------------------------------
# Task 2.5: 有机增长 capex
# ---------------------------------------------------------------------------
def organic_capex(stock_net: float, g: float) -> float:
    """g>0 时存量有机增长需供资(g × stock_net),否则现金 plug 静默吸收 BS/CF。

    g=0 时返回 0(无扩张);g<0 视为 0(收缩不产生 capex,降值走减值/报废)。
    """
    return g * stock_net if g > 0 else 0.0


# ---------------------------------------------------------------------------
# Task 2.6: ppe_capex 现金口径 + roll_da_series 装配
# ---------------------------------------------------------------------------
def compute_ppe_capex(maintenance_dep: float, expansion_capex_by_cat: dict,
                      organic: dict, year: int) -> float:
    """现金支出口径(给 FCFF/CFI):= 维持 + 扩张 capex_by_cat + 有机。

    ≠ 任何 cip_to_fixed 转固额(转固是 cip→fix 重分类,非现金)。
    缺 year 的 expansion/organic 项按 0 处理。
    """
    return (maintenance_dep
            + expansion_capex_by_cat.get(year, 0.0)
            + organic.get(year, 0.0))


def _calibrate_scale(cats: list[dict], base_reported_dep: float) -> float:
    """存量稳态折旧缩放,匹配 base 年披露 depr_fa_coga_dpba。

    policy_dep = Σ cat(base_gross*(1-salvage)/life);scale = reported/policy_dep。
    policy_dep<=0(空 cats)→ 1.0;残差过大(>20%)留 warning(实现留 TODO,本函数不报错)。
    """
    policy_dep = sum(c["base_gross"] * (1 - c["salvage_rate"]) / c["life_years"]
                     for c in cats)
    if policy_dep <= 0:
        return 1.0
    return base_reported_dep / policy_dep


def roll_da_series(sched: dict, base_bs: dict, forecast_years: int,
                   base_year: int, base_reported_dep: float) -> list[dict]:
    """主滚动:逐年产出 da_series。

    每元素含:
      period / ppe_depreciation / fix_assets_net / cip_balance / ppe_capex / ppe_capex_split

    口径(spec §6.6):
      ppe_depreciation = 存量稳态折旧(scale 校准) + 扩张 cohort 折旧(不含三类摊销)
      fix_assets_net   = 存量净值(base_net×(1+g)^t) + 扩张 cohort 累计净值
      cip_balance      = Σ各类 cip 余额(base cip 抽干 + 扩张 capex 堆积)
      ppe_capex        = 维持(=存量折旧) + 扩张 capex_by_cat + 有机;≠ 任何转固额
    """
    cats = sched["ppe"]["categories"]
    g = sched["ppe"].get("存量策略", {}).get("net_growth_rate", 0.0)
    expansion = sched.get("expansion_plan", {})
    # base_cip_to_fixed schema(与 expansion_plan 同构):{year: {cat: amt}};按 cat 提取该类 {year: amt}
    base_cip_tf = sched.get("base_cip_to_fixed", {})
    scale = _calibrate_scale(cats, base_reported_dep)

    # 预建每类 cip 状态(转固队列)
    cip_states: list[CipState] = []
    for c in cats:
        cname = c["name"]
        exp_capex_by_yr = {y: expansion.get(y, {}).get("capex_by_cat", {}).get(cname, 0.0)
                           for y in expansion}
        exp_tf_by_yr = {y: expansion.get(y, {}).get("cip_to_fixed", {}).get(cname, 0.0)
                        for y in expansion}
        c_base_tf = {y: base_cip_tf.get(y, {}).get(cname, 0.0) for y in base_cip_tf} if isinstance(base_cip_tf, dict) else {}
        cip_states.append(roll_cip(c.get("base_cip", 0.0), c_base_tf,
                                   exp_capex_by_yr, exp_tf_by_yr,
                                   c["life_years"], c["salvage_rate"], base_year + 1))

    series: list[dict] = []
    for t in range(1, forecast_years + 1):
        year = base_year + t
        # 存量稳态折旧(经 scale 校准):每类 base 政策折旧 × scale,再 (1+g)^t
        stock_dep = sum(
            stock_depreciation(
                c["base_gross"] * (1 - c["salvage_rate"]) / c["life_years"] * scale, g, t)
            for c in cats)
        # 存量净值:每类 base_net × (1+g)^t(base_net = base_gross - base_accum_dep)
        stock_net = sum(
            (c["base_gross"] - c.get("base_accum_dep", 0.0)) * (1 + g) ** t
            for c in cats)
        # 扩张 cohort 折旧 + 净值(各类转固 cohort)
        exp_dep = 0.0
        exp_cohort_net = 0.0
        cip_bal = 0.0
        for c, state in zip(cats, cip_states):
            for cohort in state.transferred_cohorts(year):
                exp_dep += cohort.dep_in_year(year)
                exp_cohort_net += cohort.net_in_year(year)
            cip_bal += state.cip_balance(year)
        total_net = stock_net + exp_cohort_net  # fix_assets_net
        maint = stock_dep  # 维持 capex = 存量稳态折旧
        org = organic_capex(stock_net, g)
        # 扩张 capex_by_cat 当年合计(给 ppe_capex)
        exp_capex_year = sum(expansion.get(year, {}).get("capex_by_cat", {}).values())
        ppe_capex = compute_ppe_capex(maint, {year: exp_capex_year}, {year: org}, year)
        series.append({
            "period": str(year),
            "ppe_depreciation": stock_dep + exp_dep,
            "fix_assets_net": total_net,
            "cip_balance": cip_bal,
            "ppe_capex": ppe_capex,
            "ppe_capex_split": {
                "maintenance": maint,
                "expansion": exp_capex_year,
                "organic": org,
            },
        })
    return series
