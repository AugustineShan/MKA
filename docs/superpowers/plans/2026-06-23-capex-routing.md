# Capex 路由修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `build_balance_sheet` 只把 PP&E 份的 capex 灌进固定资产滚存，去掉非 PP&E capex 造成的幻影折旧高估。

**Architecture:** 在 `src/calc.py` `build_balance_sheet` 中，把合并 capex 拆出 PP&E 份 `capex_ppe = capex − Σ三项摊销`，fix_assets 只滚 `capex_ppe`。`metrics["capex"]`（CFI/FCFF 用）保持完整合并 capex 不变。非 PP&E 资产稳态平推（再投资=摊销，现金流中性）。负数时 `capex_ppe` 落底 0 并发 review flag。零新参数、零 schema 变更。

**Tech Stack:** Python 3.11+（系统全局，禁止 venv），pytest，pandas。Windows + Git Bash，中文不 print（落盘看）。

**Spec:** `docs/superpowers/specs/2026-06-23-capex-routing-design.md`

---

## File Structure

- **Modify:** `src/yaml2_schema.py` — 新增 `REVIEW_FLAG_CAPEX_BELOW_NON_PPE_AMORT` 常量（line 28 旁）
- **Modify:** `src/calc.py` — import 新常量（line 33 旁）；改 `build_balance_sheet` 的 capex 路由（line 264-269）
- **Create:** `tests/test_calc_capex_routing.py` — 5 条单测
- **Modify:** `src/calc.py` 内联注释（固化稳态假设）
- **Modify:** `docs/数据流水线.md`、`docs/ARCHITECTURE.md`、`CLAUDE.md` — 文档同步

---

## Task 0: 准备分支（可选，按 feature-branch 规则）

main 上有未提交的教程改动。本任务的 commit 只 `git add` capex 路由相关文件，不碰教程改动。

**Files:** 无

- [ ] **Step 1: 建特性分支**

```bash
git checkout -b feat/capex-routing
```

> 若你选择留在 main，跳过此步即可——后续 commit 命令都是 scoped `git add`，不会动教程改动。

- [ ] **Step 2: 确认 Python 路径不指向 WindowsApps**

```bash
which python
```
Expected: 指向 `/c/Users/Sheld/AppData/Local/Programs/Python/Python*/python.exe`。若指向 WindowsApps，`source ~/.bashrc` 或用完整路径。后续命令统一用 `py`（Windows Python launcher，不踩 WindowsApps 坑）。

---

## Task 1: 核心 capex 路由（happy path）

把合并 capex 的 PP&E 份灌进 fix_assets，`metrics["capex"]` 保持完整合并口径。

**Files:**
- Test: `tests/test_calc_capex_routing.py`
- Modify: `src/calc.py:264-269`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_calc_capex_routing.py`：

```python
"""Unit tests for capex routing in build_balance_sheet.

Locks in: only the PP&E portion of combined capex rolls into fix_assets;
metrics["capex"] (used by CFI/FCFF) stays the full combined capex.
"""

from __future__ import annotations

import pytest

from src.calc import build_balance_sheet


def _income_row(revenue=1000.0, n_income_attr_p=10.0):
    return {
        "revenue": revenue,
        "oper_cost": revenue * 0.5,
        "n_income_attr_p": n_income_attr_p,
        "minority_gain": 0.0,
    }


def _prev_bs(fix_assets=50.0):
    return {
        "money_cap": 100.0,
        "undistr_porfit": 1000.0,  # 充足权益，避免负现金噪声
        "minority_int": 0.0,
        "fix_assets": fix_assets,
    }


def test_fix_assets_rolls_with_capex_ppe_not_full_capex():
    """Only capex_ppe (= combined capex − non-PP&E amortization) rolls into fix_assets."""
    yaml2 = {
        "balance_sheet": {
            "capex_pct": {"value": [0.10]},       # 合并 capex = 10% × 1000 = 100
            "depr_rate": {"value": [0.0]},         # 零折旧，隔离路由效果
            "amort_intang_assets": {"value": [3.0]},
            "use_right_asset_dep": {"value": [2.0]},
            "lt_amort_deferred_exp": {"value": [1.0]},
        }
    }
    bs_row, metrics = build_balance_sheet(yaml2, _prev_bs(), _income_row(), idx=1)

    # capex_ppe = 100 − (3+2+1) = 94; depreciation = 50 × 0.0 = 0
    # fix_assets = 50 + 94 − 0 = 144（不是 50 + 100 = 150）
    assert bs_row["fix_assets"] == pytest.approx(144.0)
    # metrics["capex"] 必须仍是完整合并 capex（CFI/FCFF 用）
    assert metrics["capex"] == pytest.approx(100.0)


def test_depreciation_not_inflated_by_non_ppE_capex():
    """Phantom depreciation removed: depreciation base is capex_ppe, not full capex."""
    yaml2 = {
        "balance_sheet": {
            "capex_pct": {"value": [0.10, 0.10]},
            "depr_rate": {"value": [0.20, 0.20]},
            "amort_intang_assets": {"value": [3.0, 3.0]},
            "use_right_asset_dep": {"value": [2.0, 2.0]},
            "lt_amort_deferred_exp": {"value": [1.0, 1.0]},
        }
    }
    bs_row1, _ = build_balance_sheet(yaml2, _prev_bs(fix_assets=0.0), _income_row(), idx=1)
    # year1: capex_ppe = 100 − 6 = 94; depr = 0 × 0.2 = 0; fix_assets = 0 + 94 = 94
    assert bs_row1["fix_assets"] == pytest.approx(94.0)

    bs_row2, metrics2 = build_balance_sheet(yaml2, bs_row1, _income_row(), idx=2)
    # year2: depr = 94 × 0.2 = 18.8（基于 capex_ppe 基数 94，不是幻影的 100 × 0.2 = 20）
    assert metrics2["depreciation"] == pytest.approx(18.8)


def test_balance_sheet_still_balances_with_capex_routing():
    """Plug 仍能配平 BS（fix_assets↓ 与 cash plug↑ 对冲）。"""
    yaml2 = {
        "balance_sheet": {
            "capex_pct": {"value": [0.10]},
            "depr_rate": {"value": [0.0]},
            "amort_intang_assets": {"value": [3.0]},
            "use_right_asset_dep": {"value": [2.0]},
            "lt_amort_deferred_exp": {"value": [1.0]},
        }
    }
    bs_row, _ = build_balance_sheet(yaml2, _prev_bs(), _income_row(), idx=1)
    residual = (
        bs_row["total_assets"]
        - bs_row["total_liab"]
        - bs_row["total_hldr_eqy_inc_min_int"]
    )
    assert abs(residual) < 1e-4


def test_asset_light_company_unchanged():
    """三项摊销旋钮全缺省（=0）时，capex_ppe == capex，行为与改前逐字相同。"""
    yaml2 = {
        "balance_sheet": {
            "capex_pct": {"value": [0.10]},
            "depr_rate": {"value": [0.0]},
            # 不设三个摊销旋钮 → get_year_float 默认 0.0
        }
    }
    bs_row, metrics = build_balance_sheet(yaml2, _prev_bs(), _income_row(), idx=1)
    # capex_ppe = 100 − 0 = 100; fix_assets = 50 + 100 = 150
    assert bs_row["fix_assets"] == pytest.approx(150.0)
    assert metrics["capex"] == pytest.approx(100.0)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `py -m pytest tests/test_calc_capex_routing.py -v`
Expected: 2 FAIL + 2 PASS。
- FAIL `test_fix_assets_rolls_with_capex_ppe_not_full_capex`：期望 144 实得 150（改前全 capex 进 fix_assets）。
- FAIL `test_depreciation_not_inflated_by_non_ppE_capex`：期望 18.8 实得 20（改前折旧基数含幻影 capex）。
- PASS `test_balance_sheet_still_balances_with_capex_routing`：plug 配平是构造性的，改前改后都平衡。
- PASS `test_asset_light_company_unchanged`：无摊销旋钮 → capex_ppe==capex，改前改后逐字相同。

pytest 退出码非 0（TDD red），即满足"先红"要求。

- [ ] **Step 3: 实现 capex 路由**

修改 `src/calc.py` `build_balance_sheet`，把 `calc.py:264-269` 这段：

```python
    capex = revenue * capex_pct
    prev_fix = max(prev_bs.get("fix_assets", 0.0), prev_bs.get("fix_assets_total", 0.0), 0.0)
    depreciation = prev_fix * depr_rate
    row["fix_assets"] = max(prev_fix + capex - depreciation, 0.0)
    if prev_bs.get("fix_assets_total", 0.0) != 0.0:
        row["fix_assets_total"] = row["fix_assets"]
```

改为：

```python
    capex = revenue * capex_pct
    # 非 PP&E 长期资产（无形/使用权/长期待摊）的稳态再投资 == 其摊销：
    # 这些资产在模型里保持平推（净变动 0），其再投资不进固定资产。
    # 只把 PP&E 份灌进 fix_assets，使折旧反映真实 PP&E 基数，
    # 而不是实际买了无形/使用权/长期待摊的那部分 capex。
    # 前提：capex_pct 必须是合并口径（c_pay_acq_const_fiolta / revenue），
    # defaults_gen 产此口径；若 yaml1 改成固定资产口径会双重扣减（无自动守卫，靠文档约束）。
    non_ppE_reinvest = (
        get_year_float(yaml2, "balance_sheet.amort_intang_assets", idx)
        + get_year_float(yaml2, "balance_sheet.use_right_asset_dep", idx)
        + get_year_float(yaml2, "balance_sheet.lt_amort_deferred_exp", idx)
    )
    capex_ppe = capex - non_ppE_reinvest
    prev_fix = max(prev_bs.get("fix_assets", 0.0), prev_bs.get("fix_assets_total", 0.0), 0.0)
    depreciation = prev_fix * depr_rate
    row["fix_assets"] = max(prev_fix + capex_ppe - depreciation, 0.0)
    if prev_bs.get("fix_assets_total", 0.0) != 0.0:
        row["fix_assets_total"] = row["fix_assets"]
```

> 注意：`metrics["capex"] = capex`（line ~303）**不动**，保持完整合并 capex 给 CFI/FCFF。

- [ ] **Step 4: 跑测试确认通过**

Run: `py -m pytest tests/test_calc_capex_routing.py -v`
Expected: 4 个 test PASS。

- [ ] **Step 5: 跑既有 calc 单测确认无回归**

Run: `py -m pytest tests/test_calc_floors.py tests/test_calc_yearly.py -v`
Expected: 全 PASS（资产轻场景行为不变，既有 floor 测试不受影响）。

- [ ] **Step 6: Commit**

```bash
git add tests/test_calc_capex_routing.py src/calc.py
git commit -m "feat(calc): route only PP&E capex into fix_assets roll

combined capex (c_pay_acq_const_fiolta) covers PP&E + intangible + ROU +
long-term deferred reinvestment. Previously all of it rolled into fix_assets,
inflating the depreciation base (phantom depreciation). Now only the PP&E
portion (capex - non-PP&E amortization) rolls into fix_assets; metrics['capex']
(CFI/FCFF) stays the full combined capex. Non-PP&E assets remain flat
(steady state: reinvestment == amortization, cash-neutral).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: 负数守卫 + review flag

`capex < Σ摊销` 时 `capex_ppe` 落底 0 并发 flag。

**Files:**
- Modify: `src/yaml2_schema.py:28`
- Modify: `src/calc.py:33`（import）+ `src/calc.py` build_balance_sheet（守卫块）
- Test: `tests/test_calc_capex_routing.py`（追加）

- [ ] **Step 1: 写失败测试**

在 `tests/test_calc_capex_routing.py` 追加：

```python
from src.yaml2_schema import REVIEW_FLAG_CAPEX_BELOW_NON_PPE_AMORT


def test_capex_below_non_ppE_amort_floors_and_flags():
    """合并 capex < 非 PP&E 摊销时，capex_ppe 落底 0 并发 review flag。"""
    yaml2 = {
        "balance_sheet": {
            "capex_pct": {"value": [0.001]},      # capex = 0.1% × 1000 = 1.0
            "depr_rate": {"value": [0.0]},
            "amort_intang_assets": {"value": [3.0]},
            "use_right_asset_dep": {"value": [2.0]},
            "lt_amort_deferred_exp": {"value": [1.0]},
        }
    }
    flags = []
    bs_row, metrics = build_balance_sheet(
        yaml2, _prev_bs(), _income_row(), idx=1, review_flags=flags
    )

    # capex=1.0 < amort_sum=6.0 → capex_ppe 落底 0; fix_assets = 50 + 0 − 0 = 50
    assert bs_row["fix_assets"] == pytest.approx(50.0)
    assert metrics["capex"] == pytest.approx(1.0)   # 完整 capex 仍 1.0
    assert any(f["code"] == REVIEW_FLAG_CAPEX_BELOW_NON_PPE_AMORT for f in flags)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `py -m pytest tests/test_calc_capex_routing.py::test_capex_below_non_ppE_amort_floors_and_flags -v`
Expected: FAIL（`ImportError: cannot import name 'REVIEW_FLAG_CAPEX_BELOW_NON_PPE_AMORT'`）。

- [ ] **Step 3: 加 flag 常量**

修改 `src/yaml2_schema.py`，在 `REVIEW_FLAG_NEGATIVE_CASH`（line 28）下一行加：

```python
REVIEW_FLAG_NEGATIVE_CASH = "negative_cash_from_plug"
REVIEW_FLAG_CAPEX_BELOW_NON_PPE_AMORT = "capex_below_non_ppE_amort"
```

- [ ] **Step 4: 在 calc.py import 新常量**

修改 `src/calc.py` line 31-37 的 import 块，把 `REVIEW_FLAG_CAPEX_BELOW_NON_PPE_AMORT` 加进去：

```python
from src.yaml2_schema import (
    DEFAULT_TERMINAL_CAPEX_DA_RATIO,
    REVIEW_FLAG_CAPEX_BELOW_NON_PPE_AMORT,
    REVIEW_FLAG_NEGATIVE_CASH,
    get_path,
    plain_value,
    read_yaml2,
)
```

- [ ] **Step 5: 加负数守卫**

在 `src/calc.py` `build_balance_sheet` 中，`capex_ppe = capex - non_ppE_reinvest` 之后、`prev_fix = ...` 之前，插入守卫：

```python
    capex_ppe = capex - non_ppE_reinvest
    if capex_ppe < 0.0:
        capex_ppe = 0.0
        if review_flags is not None:
            review_flags.append(
                {
                    "code": REVIEW_FLAG_CAPEX_BELOW_NON_PPE_AMORT,
                    "severity": "warning",
                    "period": None,
                    "message": "合并 capex 不足以覆盖非 PP&E 稳态再投资，PP&E 基数在缩，稳态假设吃紧",
                    "value": capex - non_ppE_reinvest,
                }
            )
    prev_fix = max(prev_bs.get("fix_assets", 0.0), prev_bs.get("fix_assets_total", 0.0), 0.0)
```

- [ ] **Step 6: 跑测试确认通过**

Run: `py -m pytest tests/test_calc_capex_routing.py -v`
Expected: 全 5 个 test PASS。

- [ ] **Step 7: Commit**

```bash
git add src/yaml2_schema.py src/calc.py tests/test_calc_capex_routing.py
git commit -m "feat(calc): floor capex_ppe and flag when capex < non-PP&E amort

When combined capex is insufficient to cover steady-state non-PP&E
reinvestment (amortization), capex_ppe floors at 0 and a review flag
(REVIEW_FLAG_CAPEX_BELOW_NON_PPE_AMORT) is emitted, signalling the PP&E
base is shrinking and the steady-state assumption is strained.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: 内联注释已在 Task 1 落地 — 验证

Task 1 Step 3 已把稳态假设注释写进 `build_balance_sheet`。本任务只做确认。

**Files:** `src/calc.py`

- [ ] **Step 1: 确认注释存在**

Run: `py -c "import src.calc as m, inspect; src=inspect.getsource(m.build_balance_sheet); assert '非 PP&E' in src and '稳态' in src and '合并口径' in src; print('comments OK')"`
Expected: `comments OK`

- [ ] **Step 2: py_compile 语法确认**

Run: `py -m py_compile src/calc.py src/yaml2_schema.py`
Expected: 无输出（语法 OK）

---

## Task 4: 文档同步（项目硬规则）

**Files:**
- Modify: `docs/数据流水线.md`（§第四层，capex_pct 讨论 ~line 358 附近）
- Modify: `docs/ARCHITECTURE.md`（§3.4 DCF 层 ~line 496 附近）
- Modify: `CLAUDE.md`（DCF 运行规则 ~line 137 附近）

- [ ] **Step 1: 更新 `docs/数据流水线.md`**

在 `balance_sheet.capex_pct`（~line 358）条目附近补一段说明：

```markdown
- `balance_sheet.capex_pct`（合并口径，来源 `c_pay_acq_const_fiolta / revenue`）：
  `calc.py` 把合并 capex 拆出 PP&E 份 `capex_ppe = capex − (amort_intang_assets + use_right_asset_dep + lt_amort_deferred_exp)`，
  只把 `capex_ppe` 灌进 `fix_assets` 滚存；`metrics["capex"]`（CFI/FCFF 用）仍是完整合并 capex。
  非 PP&E 资产稳态平推（再投资=摊销，现金流中性）。前提：`capex_pct` 必须合并口径，若 yaml1 改成固定资产口径会双重扣减（无自动守卫）。
```

- [ ] **Step 2: 更新 `docs/ARCHITECTURE.md` §3.4**

在 DCF 公式讨论（~line 496 `FCFF = NOPAT + D&A - CAPEX - ΔNWC`）附近补设计决策：

```markdown
**capex 路由（2026-06-23）**：`build_balance_sheet` 只把合并 capex 的 PP&E 份（`capex − Σ三项摊销`）灌进 `fix_assets` 滚存，非 PP&E capex 不再抬高固定资产基数。关键：折旧不进利润表（`oper_cost` 由 `gpm` 派生），故 DA 在 FCFF 系数是 +1 而非 +t——路由修复是一阶去高估，不是二阶税盾微调。`metrics["capex"]`（CFI/FCFF）保持完整合并口径不变。非 PP&E 资产稳态平推。`capex < Σ摊销` 时 `capex_ppe` 落底 0 并发 `REVIEW_FLAG_CAPEX_BELOW_NON_PPE_AMORT`。
```

- [ ] **Step 3: 更新 `CLAUDE.md` DCF 运行规则**

在 DCF 运行规则段（~line 137）末尾补一句：

```markdown
**capex 路由前提**：`balance_sheet.capex_pct` 必须是合并口径（`c_pay_acq_const_fiolta / revenue`，defaults_gen 默认产出）。`calc.py` 据此把 PP&E 份（`capex − Σ三项摊销`）灌进 `fix_assets`；若 yaml1 把 `capex_pct` 改成固定资产口径会双重扣减，且无自动守卫。
```

- [ ] **Step 4: Commit**

```bash
git add docs/数据流水线.md docs/ARCHITECTURE.md CLAUDE.md
git commit -m "docs: record capex routing fix and +1 DA-coefficient finding

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: 回归验证

**Files:** 无（只跑）

- [ ] **Step 1: 新乳业 forecast 重算**

Run: `py -m src.forecast --ticker 002946.SZ`
Expected: 正常完成，`Agent/forecast/` 重新生成。

- [ ] **Step 2: 落盘核对关键指标变化**

Run:
```bash
py -c "import pandas as pd; cf=pd.read_csv(r'companies/新乳业_002946/Agent/forecast/forecast_cf.csv'); print(cf[['period','depr_fa_coga_dpba']].to_string())" > /tmp/da_check.txt 2>&1; cat /tmp/da_check.txt
```
（Git Bash 中文路径用 raw；若 /tmp 不可写改 `C:/temp/da_check.txt`）
Expected: `depr_fa_coga_dpba` 列有值且较改前下降（幻影折旧被移除）。

- [ ] **Step 3: 核对 per_share 仍合理 + BS 配平**

Run:
```bash
py -c "import json; s=json.load(open(r'companies/新乳业_002946/Agent/forecast/dcf_summary.json',encoding='utf-8')); print('per_share=',s['per_share_value'])"
```
Expected: `per_share` 为有限正数、在合理区间（改前量级附近，略低）。再确认 `forecast_bs.csv` 每年 `total_assets ≈ total_liab + total_hldr_eqy_inc_min_int`。

- [ ] **Step 4: 跑完整测试套件**

Run: `py -m pytest tests/ -x -q`
Expected: 全 PASS。重点：`test_forecast_pipeline.py`（bounds-based，`1 < per_share < 200`、BS 配平、backtest 收入口径不受影响）。

- [ ] **Step 5: 若有失败，按 systematic-debugging 排查**

> 预期风险点：`test_forecast_pipeline.py` 的 `1.0 < per_share < 200.0`——本修复一阶下修 per_share，但新乳业幅度小（~0.x% 量级），应仍在区间内。若出区间，先核对 per_share 实际值再判断是修复幅度过大还是别处回归。

- [ ] **Step 6: Commit 回归产物（可选）**

> `Agent/forecast/` 与 `.modelking/` 是运行产物，按项目惯例通常不单独 commit（属公司运行时数据）。跳过即可，除非你要留快照。

---

## Done Criteria

- [ ] `tests/test_calc_capex_routing.py` 5 个 test 全 PASS
- [ ] `tests/test_calc_floors.py`、`tests/test_calc_yearly.py` 无回归
- [ ] `tests/test_forecast_pipeline.py` 仍 PASS（per_share 在区间、BS 配平、backtest passed）
- [ ] 新乳业 forecast 重算成功，`depr_fa_coga_dpba` 与 `fix_assets` 较改前下降
- [ ] `数据流水线.md` / `ARCHITECTURE.md` / `CLAUDE.md` 已同步
- [ ] 所有 commit scoped 到 capex 路由文件，未触碰教程改动

## 不做（YAGNI / 范围外，见 spec §9）

- 不做三项摊销 BS 滚动（Option R）
- 不处理"DA 加回却没在 IS 扣"的更深不一致
- 不把 `capex_ppe` 显式暴露进 CF/derived_metrics
- 不加 `capex_routing` 开关
