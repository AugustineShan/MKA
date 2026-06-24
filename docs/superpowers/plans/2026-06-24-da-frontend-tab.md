# 重资产排程前端 tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增第 7 个只读顶级 tab「重资产排程」,把 `da_schedule.yaml` / `da_facts_latest.json` / `forecast_params.yaml["da_series"]` 三层文件以声明驱动方式展示,零公司特判。

**Architecture:** workbench 新增 `_da_view(company_dir)` 只读装配 `da_view` payload(用 `yaml.safe_load` 直读 da_schedule,不走 `load_da_schedule` 的对齐校验),挂进 `/api/companies/{id}` 响应。前端 `da_view` 非 null 才渲染 tab。`DaSchedule.tsx` 四段(存量快照/扩张排程+转固/da_series结果/历史证据折叠),类别名全部从数据来。

**Tech Stack:** Python 3.11 + FastAPI(workbench)、React + Vite + TypeScript(app)、pytest、vitest 隐含(`npm run build` 走 tsc)。

**Spec:** `docs/superpowers/specs/2026-06-24-da-frontend-tab-design.md`

---

## File Structure

- **Modify** `src/workbench.py` — 新增 `_da_view(company_dir)` + `_da_base_reported_dep(company_dir, base_year)`,在 `read_company()` 响应 dict 挂 `"da_view"` 键。
- **Modify** `app/src/types.ts` — `TabKey` 加 `"da"`;新增 `DaView`/`DaCategory`/`DaSeriesPoint` 等类型;`CompanyDetail` 加 `da_view?: DaView | null`。
- **Create** `app/src/DaSchedule.tsx` — 四段只读组件,props `{ detail: CompanyDetail }`。
- **Modify** `app/src/App.tsx` — `tabs` 数组追加 `da`(条件渲染:nav 用 `tabs.filter(t => t.key !== "da" || detail?.da_view)`);`DetailView` 加 `if (tab === "da") return <DaSchedule detail={detail} />`。
- **Modify** `app/src/styles.css` — 复用 `.financial-table`/`.table-scroll`/`<details>`;新增 `.da-section`、`.da-normalization-passed`/`.da-normalization-failed`、`.da-info-banner`。
- **Create** `tests/test_workbench_da_view.py` — `_da_view` 装配单测。
- **Modify** `docs/前端设计规范.md` §2 tab 表(7 个,标注条件 tab)。
- **Modify** `docs/数据流水线.md` + `docs/ARCHITECTURE.md` — 同步 workbench 暴露 da_view。

---

## Task 1: 后端 `_da_view` 装配(TDD)

**Files:**
- Create: `tests/test_workbench_da_view.py`
- Modify: `src/workbench.py`(新增 `_da_view`、`_da_base_reported_dep`;`read_company` 挂 `da_view`)

- [ ] **Step 1: 写失败测试**

`tests/test_workbench_da_view.py`:

```python
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from src.workbench import _da_view


def _make_company(tmp_path: Path, *, da_schedule: dict | None, da_series: list | None,
                  da_facts: dict | None, with_db: bool, base_year: int = 2025) -> Path:
    company = tmp_path / "companies" / "测试公司_002946"
    agent = company / "Agent"
    (agent / "recon").mkdir(parents=True)
    (agent / ".modelking").mkdir(parents=True)
    if da_schedule is not None:
        import yaml
        (agent / "da_schedule.yaml").write_text(yaml.safe_dump(da_schedule, allow_unicode=True), encoding="utf-8")
    if da_facts is not None:
        (agent / "recon" / "da_facts_latest.json").write_text(json.dumps(da_facts, ensure_ascii=False), encoding="utf-8")
    if da_series is not None:
        import yaml
        (agent / ".modelking" / "forecast_params.yaml").write_text(
            yaml.safe_dump({"da_series": da_series}, allow_unicode=True), encoding="utf-8")
    if with_db:
        db = agent / "data.db"
        with sqlite3.connect(db) as con:
            con.execute("create table clean_annual (period text, depr_fa_coga_dpba real)")
            con.execute("insert into clean_annual values (?, ?)", (str(base_year), 424.708))
    return company


def _minimal_schedule(enabled=True, base_year=2025):
    return {
        "enabled": enabled, "base_year": base_year,
        "ppe": {"存量策略": {"mode": "perpetual_renewal", "net_growth_rate": 0.0},
                "categories": [
                    {"name": "房屋及建筑物", "life_years": 20, "salvage_rate": 0.05,
                     "base_gross": 2222.666, "base_accum_dep": 578.130, "base_cip": 0.0},
                    {"name": "机器设备", "life_years": 10, "salvage_rate": 0.05,
                     "base_gross": 2394.970, "base_accum_dep": 1395.677, "base_cip": 19.415},
                ]},
        "base_cip_to_fixed": {"2026": {"机器设备": 19.415}},
        "expansion_plan": {"2026": {"capex_by_cat": {"机器设备": 120.0}, "cip_to_fixed": {}}},
        "terminal": {"capex_da_ratio": 1.0, "perpetual_growth": 0.025},
    }


def test_da_view_none_when_no_schedule(tmp_path):
    company = _make_company(tmp_path, da_schedule=None, da_series=None, da_facts=None, with_db=False)
    assert _da_view(company, base_period="2025") is None


def test_da_view_none_when_disabled(tmp_path):
    company = _make_company(tmp_path, da_schedule=_minimal_schedule(enabled=False),
                            da_series=None, da_facts=None, with_db=False)
    assert _da_view(company, base_period="2025") is None


def test_da_view_assembles_categories_and_scale(tmp_path):
    company = _make_company(tmp_path, da_schedule=_minimal_schedule(),
                            da_series=None, da_facts=None, with_db=True)
    view = _da_view(company, base_period="2025")
    assert view is not None
    assert view["enabled"] is True
    assert view["base_year"] == 2025
    cats = view["categories"]
    assert len(cats) == 2                      # N 类 N 元素,数据驱动
    assert cats[0]["name"] == "房屋及建筑物"
    assert cats[0]["policy_dep"] == pytest.approx(2222.666 * 0.95 / 20, rel=1e-4)
    assert cats[0]["base_net"] == pytest.approx(2222.666 - 578.130, rel=1e-4)
    # policy_dep = 2222.666*0.95/20 + 2394.970*0.95/10 = 105.577 + 227.522 = 333.099
    assert view["base_reported_dep"] == pytest.approx(424.708, rel=1e-4)
    assert view["scale"] == pytest.approx(424.708 / 333.099, rel=1e-3)
    assert view["stock_strategy"]["mode"] == "perpetual_renewal"
    assert view["expansion_plan"]["2026"]["capex_by_cat"]["机器设备"] == 120.0


def test_da_view_da_series_passthrough_and_null_when_absent(tmp_path):
    # 无 forecast_params → da_series None
    company = _make_company(tmp_path, da_schedule=_minimal_schedule(),
                            da_series=None, da_facts=None, with_db=True)
    assert _da_view(company, base_period="2025")["da_series"] is None

    # 有 → 透传
    series = [{"period": "2026", "ppe_depreciation": 426.6, "fix_assets_net": 2870.7,
               "cip_balance": 200.0, "ppe_capex": 624.7,
               "ppe_capex_split": {"maintenance": 425, "expansion": 200, "organic": 0}}]
    company2 = _make_company(tmp_path / "b", da_schedule=_minimal_schedule(),
                             da_series=series, da_facts=None, with_db=True)
    view = _da_view(company2, base_period="2025")
    assert view["da_series"] == series


def test_da_view_facts_passthrough(tmp_path):
    facts = {"ppe_detail": {"2025": {}}, "roll_forward_checks": [], "policy": {"source_year": 2025}}
    company = _make_company(tmp_path, da_schedule=_minimal_schedule(),
                            da_series=None, da_facts=facts, with_db=True)
    view = _da_view(company, base_period="2025")
    assert view["facts"] == facts


def test_da_view_align_warning_when_base_year_mismatch(tmp_path):
    company = _make_company(tmp_path, da_schedule=_minimal_schedule(base_year=2024),
                            da_series=None, da_facts=None, with_db=True, base_year=2024)
    view = _da_view(company, base_period="2025")   # defaults base_period=2025, schedule base_year=2024
    assert view is not None
    assert view.get("align_warning")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `py -m pytest tests/test_workbench_da_view.py -v`
Expected: FAIL(`ImportError: cannot import name '_da_view'`)

- [ ] **Step 3: 实现 `_da_view` + `_da_base_reported_dep`**

在 `src/workbench.py` 已有 `_read_yaml`/`_read_json`/`_read_text` 附近新增(用 `yaml.safe_load` 直读,不走 `load_da_schedule`):

```python
def _da_base_reported_dep(company_dir: Path, base_year: str) -> float | None:
    """base 年现金流量表 PP&E 折旧(depr_fa_coga_dpba),与 forecast._maybe_roll_da_series 同源。"""
    db_path = company_db_path(company_dir)
    if not db_path.exists():
        return None
    try:
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "select depr_fa_coga_dpba from clean_annual where period = ?", (str(base_year),)
            ).fetchone()
    except sqlite3.Error:
        return None
    return float(row[0]) if row and row[0] is not None else None


def _da_view(company_dir: Path, base_period: str) -> dict[str, Any] | None:
    """只读装配重资产排程展示数据。enabled/false/缺失 → None(前端不渲染 tab)。"""
    sched_path = da_schedule_path(company_dir)
    if not sched_path.exists():
        return None
    sched = _read_yaml(sched_path)          # yaml.safe_load 直读,不走 load_da_schedule 对齐校验
    if not sched.get("enabled", False):
        return None
    base_year = sched.get("base_year")
    base_year_str = str(base_year) if base_year is not None else base_period
    align_warning = None
    if base_year_str != str(base_period)[:4]:
        align_warning = f"da_schedule.base_year={base_year} ≠ defaults.base_period={base_period}"

    cats_in = sched.get("ppe", {}).get("categories", []) or []
    cats = []
    for c in cats_in:
        gross = float(c.get("base_gross") or 0.0)
        salv = float(c.get("salvage_rate") or 0.0)
        life = float(c.get("life_years") or 0.0)
        accum = float(c.get("base_accum_dep") or 0.0)
        policy_dep = gross * (1 - salv) / life if life else 0.0
        cats.append({
            "name": c.get("name"),
            "life_years": c.get("life_years"),
            "salvage_rate": salv,
            "base_gross": gross,
            "base_accum_dep": accum,
            "base_net": gross - accum,
            "base_cip": float(c.get("base_cip") or 0.0),
            "policy_dep": policy_dep,
        })
    policy_dep_total = sum(c["policy_dep"] for c in cats)
    reported = _da_base_reported_dep(company_dir, base_year_str)
    scale = (reported / policy_dep_total) if (reported is not None and policy_dep_total > 0) else None

    # da_series:从 .modelking/forecast_params.yaml["da_series"] 透传
    fp_path = modelking_dir(company_dir) / "forecast_params.yaml"
    da_series = None
    if fp_path.exists():
        fp = _read_yaml(fp_path)
        ds = fp.get("da_series")
        if isinstance(ds, list):
            da_series = ds

    # facts:da_facts_latest.json 透传(单位元,前端展示时按需 ÷1e6;此处保持原样)
    facts_path = recon_dir(company_dir) / "da_facts_latest.json"
    facts = _read_json(facts_path) if facts_path.exists() else None

    return {
        "enabled": True,
        "base_year": base_year,
        "align_warning": align_warning,
        "stock_strategy": sched.get("ppe", {}).get("存量策略", {}) or {},
        "categories": cats,
        "scale": scale,
        "base_reported_dep": reported,
        "base_cip_to_fixed": sched.get("base_cip_to_fixed", {}) or {},
        "expansion_plan": sched.get("expansion_plan", {}) or {},
        "terminal": sched.get("terminal", {}) or {},
        "da_series": da_series,
        "normalization": _da_normalization(da_series, sched),
        "facts": facts,
    }


def _da_normalization(da_series: list | None, sched: dict) -> dict | None:
    """重算终值归一化门(da_roll.normalization_gate),da_series 缺失→None。"""
    if not da_series:
        return None
    try:
        from src.da_roll import normalization_gate
        g = float(sched.get("ppe", {}).get("存量策略", {}).get("net_growth_rate", 0.0) or 0.0)
        pg = float(sched.get("terminal", {}).get("perpetual_growth", 0.0) or 0.0)
        passed, reason = normalization_gate(da_series, g, pg)
        return {"passed": passed, "reason": reason}
    except Exception as exc:  # 展示层不阻塞,诚实记错
        return {"passed": None, "reason": f"normalization_gate error: {exc}"}
```

并在 `src/workbench.py` 顶部 import 区(`from src.company_paths import (...)`)补 `da_schedule_path`、`recon_dir`(若未导入)。

- [ ] **Step 4: 在 `read_company()` 响应挂 `da_view`**

在 `read_company` 函数(约 `src/workbench.py:1956`)的 `return { ... }` dict 里追加一行(放在 `"materials"` 后或 `"quarterly_view"` 旁):

```python
        "da_view": _da_view(company_dir, base_period=_base_period_for_company(company_dir)),
```

并新增小助手(读 defaults.yaml base_period;若缺用最新 clean_annual 年份):

```python
def _base_period_for_company(company_dir: Path) -> str:
    defaults = _read_yaml(company_defaults_path(company_dir))
    bp = defaults.get("base_period")
    if bp:
        return str(bp)
    return ""   # _da_view 在 base_period 为空时 align_warning 会触发,不影响装配
```

(`company_defaults_path` 已在 workbench import。)

- [ ] **Step 5: 运行测试确认通过**

Run: `py -m pytest tests/test_workbench_da_view.py -v`
Expected: 6 passed

- [ ] **Step 6: py_compile + 提交**

```bash
py -m py_compile src/workbench.py
git add tests/test_workbench_da_view.py src/workbench.py
git commit -m "feat(workbench): assemble da_view payload from da_schedule/facts/da_series"
```

---

## Task 2: 前端类型 + tab 接线

**Files:**
- Modify: `app/src/types.ts`
- Modify: `app/src/App.tsx`

- [ ] **Step 1: types.ts — TabKey + DaView 类型**

`TabKey` 改为:
```ts
export type TabKey = "overview" | "yaml1" | "quarterly" | "statements" | "dcf" | "reverse" | "da";
```

新增类型(放 `CompanyDetail` 之前):
```ts
export interface DaCategory {
  name: string;
  life_years: number;
  salvage_rate: number;
  base_gross: number;
  base_accum_dep: number;
  base_net: number;
  base_cip: number;
  policy_dep: number;
}
export interface DaSeriesPoint {
  period: string;
  ppe_depreciation: number;
  fix_assets_net: number;
  cip_balance: number;
  ppe_capex: number;
  ppe_capex_split: { maintenance: number; expansion: number; organic: number };
}
export interface DaView {
  enabled: boolean;
  base_year: number;
  align_warning: string | null;
  stock_strategy: { mode?: string; net_growth_rate?: number };
  categories: DaCategory[];
  scale: number | null;
  base_reported_dep: number | null;
  base_cip_to_fixed: Record<string, Record<string, number>>;
  expansion_plan: Record<string, { capex_by_cat: Record<string, number>; cip_to_fixed: Record<string, number> }>;
  terminal: { capex_da_ratio: number; perpetual_growth: number };
  da_series: DaSeriesPoint[] | null;
  normalization: { passed: boolean | null; reason: string } | null;
  facts: Record<string, unknown> | null;
}
```

`CompanyDetail` 接口加字段:`da_view?: DaView | null;`

- [ ] **Step 2: App.tsx — tabs 追加 + 条件渲染 + DetailView 分支**

`tabs` 数组(约 `App.tsx:41`)末尾追加:
```ts
  { key: "da", label: "重资产排程" },
```

nav 渲染(约 `App.tsx:4047`)改为按 da_view 过滤:
```tsx
          {tabs.filter((item) => item.key !== "da" || Boolean(detail?.da_view)).map((item) => (
```

`DetailView`(约 `App.tsx:3950` `reverse` 分支后)加:
```tsx
  if (tab === "da" && detail.da_view) return <DaSchedule detail={detail} />;
```

顶部 import 加:`import DaSchedule from "./DaSchedule";`(若用默认导出)。

- [ ] **Step 3: 暂不 build(组件下个 Task 才建),先提交类型+接线**

```bash
git add app/src/types.ts app/src/App.tsx
git commit -m "feat(app): wire da tab key + conditional render (component next)"
```

---

## Task 3: `DaSchedule.tsx` 四段组件

**Files:**
- Create: `app/src/DaSchedule.tsx`

- [ ] **Step 1: 写组件(四段,只读,数据驱动)**

`app/src/DaSchedule.tsx`:

```tsx
import type { CompanyDetail, DaCategory } from "./types";

const fmt = (v: number | null | undefined, digits = 1): string =>
  v == null || Number.isNaN(v) ? "" : v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
const pct = (v: number | null | undefined): string =>
  v == null ? "" : `${(v * 100).toFixed(1)}%`;

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="da-section">
      <h3 className="da-section-title">{title}</h3>
      {children}
    </section>
  );
}

export default function DaSchedule({ detail }: { detail: CompanyDetail }) {
  const da = detail.da_view;
  if (!da) return null;
  const years = Object.keys(da.expansion_plan).sort();
  const cats = da.categories;

  return (
    <div className="da-tab">
      <div className="da-info-banner">
        ⓘ 这是 /da 产出的排程展示。改假设请跑 <code>/da {detail.summary.ticker ?? ""}</code>;
        重算请跑 <code>py -m src.forecast --ticker {detail.summary.ticker ?? ""}</code>
      </div>

      {da.align_warning ? <div className="error-banner">{da.align_warning}</div> : null}

      <Section title={`§1 PP&E 存量快照 (base ${da.base_year})`}>
        <div className="activity">
          存量策略: {da.stock_strategy.mode ?? "—"} · g={da.stock_strategy.net_growth_rate ?? 0}
          {da.scale != null && da.base_reported_dep != null
            ? ` · scale=${da.scale.toFixed(3)} (披露 ${fmt(da.base_reported_dep)} / policy ${fmt(da.categories.reduce((s, c) => s + c.policy_dep, 0))})`
            : " · scale 待补(缺 clean_annual 折旧)"}
        </div>
        <div className="table-scroll">
          <table className="financial-table">
            <thead>
              <tr>
                <th>类别</th><th>年限</th><th>残值率</th><th>原值</th>
                <th>累计折旧</th><th>净值</th><th>CIP</th><th>政策年折旧</th>
              </tr>
            </thead>
            <tbody>
              {cats.map((c: DaCategory) => (
                <tr key={c.name}>
                  <td>{c.name}</td>
                  <td className="numeric">{c.life_years}</td>
                  <td className="numeric">{pct(c.salvage_rate)}</td>
                  <td className="numeric">{fmt(c.base_gross)}</td>
                  <td className="numeric">{fmt(c.base_accum_dep)}</td>
                  <td className="numeric">{fmt(c.base_net)}</td>
                  <td className="numeric">{fmt(c.base_cip)}</td>
                  <td className="numeric">{fmt(c.policy_dep)}</td>
                </tr>
              ))}
              <tr className="subtotal-row">
                <td>合计</td><td /><td /><td className="numeric">{fmt(cats.reduce((s, c) => s + c.base_gross, 0))}</td>
                <td className="numeric">{fmt(cats.reduce((s, c) => s + c.base_accum_dep, 0))}</td>
                <td className="numeric">{fmt(cats.reduce((s, c) => s + c.base_net, 0))}</td>
                <td className="numeric">{fmt(cats.reduce((s, c) => s + c.base_cip, 0))}</td>
                <td className="numeric">{fmt(cats.reduce((s, c) => s + c.policy_dep, 0))}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </Section>

      <Section title="§2 扩张 capex 排程 + 转固">
        <CapexMatrix title="capex_by_cat (投资)" years={years} cats={cats}
          cell={(y, c) => da.expansion_plan[y]?.capex_by_cat?.[c] ?? null} />
        <CapexMatrix title="cip_to_fixed (转固起折旧)" years={years} cats={cats}
          cell={(y, c) => da.expansion_plan[y]?.cip_to_fixed?.[c] ?? null} />
        <div className="table-scroll">
          <table className="financial-table">
            <thead><tr><th>存量 CIP 转固</th>{years.map((y) => <th key={y}>{y}E</th>)}</tr></thead>
            <tbody>
              {cats.map((c) => (
                <tr key={c.name}>
                  <td>{c.name}</td>
                  {years.map((y) => <td className="numeric" key={y}>{fmt(da.base_cip_to_fixed[y]?.[c.name] ?? null)}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <Section title="§3 da_series 结果 (逐年)">
        {da.da_series == null ? (
          <div className="error-banner">请先 <code>py -m src.forecast --ticker {detail.summary.ticker ?? ""}</code> 重跑生成 da_series</div>
        ) : (
          <>
            <div className="table-scroll">
              <table className="financial-table">
                <thead>
                  <tr>
                    <th>年</th><th>PP&E 折旧</th><th>固定资产净值</th><th>CIP 余额</th>
                    <th>capex 合计</th><th>维持</th><th>扩张</th><th>有机</th>
                  </tr>
                </thead>
                <tbody>
                  {da.da_series.map((p) => (
                    <tr key={p.period}>
                      <td>{p.period}E</td>
                      <td className="numeric">{fmt(p.ppe_depreciation)}</td>
                      <td className="numeric">{fmt(p.fix_assets_net)}</td>
                      <td className="numeric">{fmt(p.cip_balance)}</td>
                      <td className="numeric">{fmt(p.ppe_capex)}</td>
                      <td className="numeric">{fmt(p.ppe_capex_split.maintenance)}</td>
                      <td className="numeric">{fmt(p.ppe_capex_split.expansion)}</td>
                      <td className="numeric">{fmt(p.ppe_capex_split.organic)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {da.normalization ? (
              <div className={da.normalization.passed ? "da-normalization-passed" : "da-normalization-failed"}>
                终值归一化门: {da.normalization.passed ? "passed" : "failed"} — {da.normalization.reason}
              </div>
            ) : null}
          </>
        )}
      </Section>

      <Section title="§4 历史 roll-forward 证据 (da_facts)">
        {da.facts == null ? (
          <div className="activity">无 da_facts_latest.json</div>
        ) : (
          <details>
            <summary>展开历史 roll-forward (per 类别 × 近 5 年) + policy</summary>
            <pre className="da-facts-raw">{JSON.stringify(da.facts, null, 2)}</pre>
          </details>
        )}
      </Section>
    </div>
  );
}

function CapexMatrix({ title, years, cats, cell }: {
  title: string; years: string[]; cats: DaCategory[];
  cell: (year: string, cat: DaCategory) => number | null;
}) {
  return (
    <div className="table-scroll">
      <div className="activity">{title}</div>
      <table className="financial-table">
        <thead><tr><th>类别</th>{years.map((y) => <th key={y}>{y}E</th>)}</tr></thead>
        <tbody>
          {cats.map((c) => (
            <tr key={c.name}>
              <td>{c.name}</td>
              {years.map((y) => <td className="numeric" key={y}>{fmt(cell(y, c))}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

> §4 第一版用 `<pre>` 展 raw facts JSON(power user 兜底,零丢失)。后续可按 `roll_forward_checks[]` 真实键结构化成表,但首版 YAGNI——先有展示,结构化留迭代。

- [ ] **Step 2: styles.css — 新增 DA 样式(复用为主)**

`app/src/styles.css` 末尾追加:
```css
.da-tab { display: flex; flex-direction: column; gap: 24px; padding: 0 0 24px; }
.da-section { display: flex; flex-direction: column; gap: 8px; }
.da-section-title { font-size: 13px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--secondary); margin: 0; }
.da-info-banner { font-size: 12px; color: var(--secondary); border: 1px solid var(--border); border-radius: 8px; padding: 10px 14px; }
.da-info-banner code { background: var(--surface); padding: 1px 4px; border-radius: 4px; }
.da-normalization-passed { color: var(--blue); font-size: 12px; }
.da-normalization-failed { color: var(--red); font-size: 12px; }
.da-facts-raw { font-family: var(--mono); font-size: 11px; white-space: pre-wrap; max-height: 400px; overflow: auto; background: #fafafa; padding: 12px; border-radius: 8px; border: 1px solid var(--border); }
.subtotal-row td { font-weight: 600; background: #f7f7fa; }
```

- [ ] **Step 3: build 验证 TS**

Run: `cd app && npm run build`
Expected: build 成功(tsc 无类型错误)

- [ ] **Step 4: 提交**

```bash
git add app/src/DaSchedule.tsx app/src/styles.css
git commit -m "feat(app): DaSchedule read-only tab (4 sections, declaration-driven)"
```

---

## Task 4: 文档同步

**Files:**
- Modify: `docs/前端设计规范.md` §2
- Modify: `docs/数据流水线.md`
- Modify: `docs/ARCHITECTURE.md`

- [ ] **Step 1: 前端设计规范 §2 tab 表**

把"固定五个顶级 tab"改为"固定七个顶级 tab(第7个「重资产排程」为条件 tab,仅 `da_view` 非 null 即 `da_schedule.enabled` 时渲染)",tab 表末尾追加:
```
| 7 | 重资产排程 | DA 排程展示(只读) | da_view(da_schedule + da_facts + da_series) |
```
并在 §9 禁忌清单补一条:`❌ 在 DaSchedule renderer 里出现公司名/业务线名/类别名字面量(类别名只能来自 categories[].name)`。

- [ ] **Step 2: 数据流水线.md + ARCHITECTURE.md**

在 workbench 节说明新增:`workbench.py` 只读装配 `da_view`(`da_schedule.yaml` + `recon/da_facts_latest.json` + `.modelking/forecast_params.yaml["da_series"]`),`/api/companies/{id}` 响应挂 `da_view`,前端第7 tab 条件渲染。

- [ ] **Step 3: 提交**

```bash
git add docs/前端设计规范.md docs/数据流水线.md docs/ARCHITECTURE.md
git commit -m "docs: sync DA frontend tab (7th conditional tab, da_view payload)"
```

---

## Task 5: 端到端验证

- [ ] **Step 1: 后端单测全过**

Run: `py -m pytest tests/test_workbench_da_view.py -v`
Expected: 6 passed

- [ ] **Step 2: 前端 build**

Run: `cd app && npm run build`
Expected: 成功

- [ ] **Step 3: 真实数据烟测(新乳业,需先重跑 forecast 生成 da_series)**

```bash
# 若 .modelking/forecast_params.yaml 还没 da_series 键(本次 /da 落盘后未重跑):
py -m src.forecast --ticker 002946.SZ
# 杀 8765 僵尸进程后起 workbench
netstat -ano | grep :8765 || true
py -m src.workbench
```
浏览器开 http://127.0.0.1:8765,选新乳业,确认:
- 第7 tab「重资产排程」出现。
- §1 4 类 + 合计,scale≈0.952。
- §2 两张年×类别矩阵 + 存量 CIP 转固小表。
- §3 da_series 逐年 2026-2033,终值门 passed。
- §4 折叠可展开 raw facts。
- 选一家轻资产公司(如安克创新)确认第7 tab 不出现。

- [ ] **Step 4: 通用性自检**

```bash
grep -nE "新乳业|乳业|房屋及建筑物|机器设备|002946" app/src/DaSchedule.tsx
```
Expected: 无输出(renderer 内零公司/类别字面量)。

---

## 风险与已知限制(非本 plan 范围)

- **生产性生物资产(奶牛)折旧未进 da_schedule**:新乳业 `depr_fa_coga_dpba`(425M)含生物资产折旧,但 da_schedule 只声明了 4 类 PP&E(policy_dep 446,scale 0.95 偶然接近 1)。这是 `/da` skill 的声明覆盖问题(da_facts 按需扩生物资产明细),非前端问题。前端如实展示 scale;若 scale 偏离 1 过大,分析师可见信号。留待 /da skill 迭代。
- §4 首版用 raw JSON 兜底,结构化 roll-forward 表留迭代(YAGNI)。
