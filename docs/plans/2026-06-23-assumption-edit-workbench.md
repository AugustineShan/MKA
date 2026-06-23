# Universal Assumption Edit Workbench Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Turn the current read-only core-assumption page into a universal assumption-edit workbench that can preview all yaml1 knobs, show profit impact beside revenue drivers, and generate a `/ka` prompt for canonical write-back.

**Architecture:** Keep `核心假设.md -> yaml1 -> forecast` as the canonical chain. Frontend edits create an in-memory yaml1 overlay and run a preview forecast without touching `核心假设.md`, `yaml1_*.yaml`, or `Agent/forecast/`; confirmed edits generate a structured change brief for `/ka`, then `/comp` remains responsible for producing the official yaml1 and DCF output.

**Tech Stack:** Python FastAPI workbench (`src/workbench.py`), yaml1 compiler runtime (`src/yaml1_cleaner.py`, `src/forecast.py`, `src/calc.py`), React + TypeScript (`app/src/App.tsx`, `app/src/types.ts`), pytest, npm build.

---

## Current Context

The current workbench reads yaml1 and forecast outputs:

- `src/workbench.py` exposes `yaml1_revenue_view`, `yaml1_assumptions_view`, `full_statement_sheets`, `dcf_summary`, and `dcf_detail`.
- `app/src/App.tsx` renders the core-assumption page with separate internal subtabs for revenue split and key assumptions.
- `src/yaml1_cleaner.clean_yaml1()` currently accepts file paths, loads yaml1 from disk, resolves it into forecast params, and returns a report.
- `src.forecast.run_company_forecast()` writes official outputs under `Agent/forecast/`.

The new feature must not directly edit official files during preview.

---

## Data Model

Add a backend-owned editable assumption model. The frontend must not infer editability from labels.

```ts
export type EditableAssumptionCell = {
  year: string;
  pointer: string;
  value: number | null;
};

export type EditableAssumption = {
  id: string;
  label: string;
  group: "result" | "revenue_driver" | "standard_knob" | "terminal" | "other";
  path: string;
  family?: string | null;
  unit: "pct" | "decimal" | "abs_mn" | "number" | "unknown";
  format: "percent" | "number" | "integer";
  source: "yaml1_top_level_values" | "yaml1_revenue_driver" | "yaml1_terminal";
  cells: EditableAssumptionCell[];
  note?: string | null;
  src?: string | null;
};

export type AssumptionPatch = {
  pointer: string;
  old_value: number | null;
  new_value: number | null;
};
```

Pointer examples:

- Top-level yaml1 value: `/income.gpm/values/0`
- Nested revenue driver: `/income.revenue/segments/低温鲜奶/factors/0/projection/values/0`
- Terminal scalar: `/terminal/perpetual_growth`

Important: yaml1 top-level keys such as `income.gpm` contain dots. Treat them as literal JSON object keys in the first pointer segment.

---

## Task 1: Refactor yaml1_cleaner for In-Memory Preview

**Files:**
- Modify: `src/yaml1_cleaner.py`
- Test: `tests/test_yaml1_cleaner.py`

**Step 1: Add a failing test**

Add a test proving `clean_yaml1_data()` can run from an already-loaded yaml1 dict and does not require writing a temp yaml1 file.

```python
def test_clean_yaml1_data_matches_file_path(sample_company_paths):
    yaml1_path, defaults_path, db_path = sample_company_paths
    yaml1_data = load_yaml(yaml1_path)

    from_path = clean_yaml1(yaml1_path, defaults_path, db_path)
    from_data = clean_yaml1_data(
        yaml1_data,
        defaults_path,
        db_path,
        yaml1_label=str(yaml1_path),
    )

    assert from_data.forecast_params == from_path.forecast_params
    assert from_data.report["backtest"]["status"] == from_path.report["backtest"]["status"]
```

If no `sample_company_paths` fixture exists, create a small fixture using `tests/fixtures/company_002946/Agent/yaml1_新乳业_20260616.yaml`, its `defaults.yaml`, and `data.db`.

**Step 2: Run the test**

Run:

```bash
py -m pytest tests/test_yaml1_cleaner.py::test_clean_yaml1_data_matches_file_path -q
```

Expected: fail because `clean_yaml1_data` does not exist.

**Step 3: Implement `clean_yaml1_data()`**

In `src/yaml1_cleaner.py`, split `clean_yaml1()` into a path loader plus an in-memory helper.

```python
def clean_yaml1_data(
    yaml1: dict[str, Any],
    defaults_path: str | Path,
    clean_annual_path: str | Path,
    *,
    yaml1_label: str = "<memory>",
) -> CleanResult:
    yaml2 = load_yaml(defaults_path)
    clean_annual = load_clean_annual(clean_annual_path)
    # Move the existing body of clean_yaml1 here, replacing load_yaml(yaml1_path)
    # with the yaml1 argument and using yaml1_label in reports.
```

Then keep the old public API:

```python
def clean_yaml1(yaml1_path: str | Path, defaults_path: str | Path, clean_annual_path: str | Path) -> CleanResult:
    yaml1 = load_yaml(yaml1_path)
    return clean_yaml1_data(yaml1, defaults_path, clean_annual_path, yaml1_label=str(yaml1_path))
```

**Step 4: Run regression tests**

Run:

```bash
py -m pytest tests/test_yaml1_cleaner.py tests/test_forecast_pipeline.py -q
```

Expected: pass.

---

## Task 2: Backend Editable Assumption Extraction

**Files:**
- Modify: `src/workbench.py`
- Create: `tests/test_workbench_assumption_editor.py`

**Step 1: Write extraction tests**

Create tests for three classes of editable assumptions:

```python
def test_editable_assumptions_include_top_level_values():
    data = {
        "meta": {"horizon": [2025, 2026]},
        "income.gpm": {"values": [0.29, 0.30], "src": "test"},
    }
    rows = _editable_assumptions(data)
    assert any(row["path"] == "income.gpm" for row in rows)
    assert rows[0]["cells"][0]["pointer"] == "/income.gpm/values/0"


def test_editable_assumptions_include_revenue_driver_values():
    data = {
        "meta": {"horizon": [2025, 2026]},
        "income.revenue": {
            "kind": "decomposition",
            "segments": {
                "低温鲜奶": {
                    "revenue_family": "factor_product",
                    "factors": [
                        {"key": "volume", "projection": {"kind": "yoy", "values": [0.07, 0.06]}},
                        {"key": "price", "projection": {"kind": "yoy", "values": [0.003, 0.003]}},
                    ],
                }
            },
        },
    }
    rows = _editable_assumptions(data)
    labels = {row["label"] for row in rows}
    assert "低温鲜奶 · volume" in labels
    assert "低温鲜奶 · price" in labels
```

Also test terminal scalar extraction if the project wants terminal edit in phase one:

```python
def test_editable_assumptions_include_terminal_growth():
    data = {"terminal": {"perpetual_growth": 0.025}}
    rows = _editable_assumptions(data)
    assert any(row["pointer"] == "/terminal/perpetual_growth" for row in rows)
```

**Step 2: Implement `_editable_assumptions()`**

Add helper functions in `src/workbench.py`:

```python
def _editable_assumptions(data: dict[str, Any]) -> list[dict[str, Any]]:
    years = _years_from_yaml1(data)
    rows = []
    rows.extend(_editable_top_level_value_knobs(data, years))
    rows.extend(_editable_revenue_driver_knobs(data, years))
    rows.extend(_editable_terminal_knobs(data))
    return rows
```

Rules:

- Include every top-level yaml1 item where `payload` is a dict and `payload.values` is a list.
- Exclude `meta`, `stash`, and `income.revenue` from the top-level pass.
- Recursively walk `income.revenue.segments`; for every factor or leaf projection with numeric `values`, create an editable row.
- Include `knobs.margin` if present on revenue leaves.
- Do not special-case company names or segment names.

**Step 3: Return editables in company detail**

In `read_company()`, add:

```python
"editable_assumptions": _editable_assumptions(yaml1_data) if yaml1_data else [],
```

**Step 4: Run tests**

Run:

```bash
py -m pytest tests/test_workbench_assumption_editor.py -q
```

Expected: pass.

---

## Task 3: Patch Application and Preview Forecast Endpoint

**Files:**
- Modify: `src/workbench.py`
- Test: `tests/test_workbench_assumption_editor.py`

**Step 1: Write tests for safe patch application**

```python
def test_apply_assumption_patches_updates_only_requested_pointer():
    data = {"income.gpm": {"values": [0.29, 0.30]}}
    patched = _apply_assumption_patches(
        data,
        [{"pointer": "/income.gpm/values/1", "old_value": 0.30, "new_value": 0.31}],
    )
    assert patched["income.gpm"]["values"] == [0.29, 0.31]
    assert data["income.gpm"]["values"] == [0.29, 0.30]
```

Add guard tests:

- Reject pointer not returned by `_editable_assumptions`.
- Reject old value mismatch.
- Reject non-numeric new value for numeric cells.

**Step 2: Implement patch helpers**

Use a small JSON Pointer implementation inside `src/workbench.py`; do not pull in a new dependency.

```python
def _decode_pointer_segment(segment: str) -> str:
    return segment.replace("~1", "/").replace("~0", "~")


def _apply_assumption_patches(data: dict[str, Any], patches: list[dict[str, Any]]) -> dict[str, Any]:
    patched = copy.deepcopy(data)
    editable = {
        cell["pointer"]: cell
        for row in _editable_assumptions(data)
        for cell in row.get("cells", [])
    }
    for patch in patches:
        pointer = str(patch.get("pointer"))
        if pointer not in editable:
            raise HTTPException(status_code=400, detail=f"Unsupported editable pointer: {pointer}")
        # Check old_value matches, then set new_value.
    return patched
```

**Step 3: Add preview endpoint**

Add Pydantic models:

```python
class AssumptionPatchPayload(BaseModel):
    pointer: str
    old_value: float | None = None
    new_value: float | None = None


class AssumptionPreviewPayload(BaseModel):
    patches: list[AssumptionPatchPayload]
```

Endpoint:

```python
@app.post("/api/companies/{company_id}/assumption-preview")
def assumption_preview(company_id: str, payload: AssumptionPreviewPayload) -> dict[str, Any]:
    company_dir = _company_dir(company_id)
    yaml1_path = _latest_yaml1(company_dir)
    if not yaml1_path:
        raise HTTPException(status_code=404, detail="yaml1_*.yaml was not found")

    yaml1_data = _read_yaml(yaml1_path)
    patched_yaml1 = _apply_assumption_patches(
        yaml1_data,
        [item.model_dump() for item in payload.patches],
    )
    cleaned = clean_yaml1_data(
        patched_yaml1,
        company_defaults_path(company_dir),
        company_db_path(company_dir),
        yaml1_label=f"{yaml1_path}#preview",
    )
    build = build_forecast_statements(cleaned.forecast_params)
    result = value_from_statements(
        build,
        wacc=as_float(get_path(cleaned.forecast_params, "model.wacc")),
        terminal_growth=as_float(get_path(cleaned.forecast_params, "model.terminal_growth")),
        terminal_capex_da_ratio=as_float(get_path(cleaned.forecast_params, "model.terminal_capex_da_ratio"), DEFAULT_TERMINAL_CAPEX_DA_RATIO),
    )
    return _preview_response(company_dir, cleaned, result, build)
```

`_preview_response` should shape enough data for the UI:

- `dcf_summary`
- `dcf_detail`
- `statement_sheets` from in-memory DataFrames
- `result_rows` for revenue, revenue yoy, net profit, attributable net profit, net margin, net profit yoy
- `warnings` and `errors`

Do not write `Agent/forecast/`, `Agent/.modelking/forecast_params.yaml`, or any official yaml1 file.

**Step 4: Run backend tests**

Run:

```bash
py -m pytest tests/test_workbench_assumption_editor.py tests/test_yaml1_cleaner.py tests/test_forecast_pipeline.py -q
```

Expected: pass.

---

## Task 4: Frontend Types and API Client

**Files:**
- Modify: `app/src/types.ts`
- Modify: `app/src/App.tsx`

**Step 1: Add TypeScript types**

Add:

```ts
export type EditableAssumptionCell = {
  year: string;
  pointer: string;
  value: number | null;
};

export type EditableAssumption = {
  id: string;
  label: string;
  group: "result" | "revenue_driver" | "standard_knob" | "terminal" | "other";
  path: string;
  family?: string | null;
  unit: "pct" | "decimal" | "abs_mn" | "number" | "unknown";
  format: "percent" | "number" | "integer";
  source: string;
  cells: EditableAssumptionCell[];
  note?: string | null;
  src?: string | null;
};

export type AssumptionPatch = {
  pointer: string;
  old_value: number | null;
  new_value: number | null;
};

export type AssumptionPreview = {
  dcf_summary?: Record<string, unknown> | null;
  dcf_detail?: DcfDetailRow[];
  statement_sheets?: StatementSheet[];
  result_rows: StatementRow[];
  warnings?: Array<Record<string, unknown>>;
  errors?: Array<Record<string, unknown>>;
};
```

Extend `CompanyDetail` with:

```ts
editable_assumptions?: EditableAssumption[];
```

**Step 2: Add API call**

Add helper:

```ts
async function previewAssumptions(companyId: string, patches: AssumptionPatch[]): Promise<AssumptionPreview> {
  return apiPostJson<AssumptionPreview>(
    `/api/companies/${encodeURIComponent(companyId)}/assumption-preview`,
    { patches },
  );
}
```

**Step 3: Run TypeScript**

Run:

```bash
npm run build
```

Expected: fail until UI consumers are added or unused imports are cleaned up.

---

## Task 5: Merge Revenue Split and Key Assumptions Into One Workbench

**Files:**
- Modify: `app/src/App.tsx`
- Modify: `app/src/styles.css`

**Step 1: Remove internal revenue/assumption subtabs**

Inside the core-assumption view, stop rendering revenue split and key assumptions as mutually exclusive internal tabs. Keep top-level app tabs unchanged.

Replace the internal flow with:

1. Result target block
2. Revenue split block
3. Editable assumptions block
4. Reference / disclosure blocks

**Step 2: Add result rows below total revenue**

Build result rows from `fullStatementSheets` by default and from preview state when edits exist:

- `营业收入`
- `同比增长`
- `归母净利润` using `n_income_attr_p`, fallback `n_income`
- `净利润`
- `净利率`
- `净利润同比`

Implementation shape:

```ts
function buildResultGroups(fullStatementSheets?: StatementSheet[], preview?: AssumptionPreview | null): AxisGroup[] {
  const sheets = preview?.statement_sheets ?? fullStatementSheets ?? [];
  const fullIs = sheets.find((sheet) => sheet.key === "is");
  // Reuse statementValue(), calcYoy(), ratioToRevenue() helpers.
}
```

Place the result group immediately under the total revenue block in the same unified year table. This addresses the user workflow: adjust revenue and assumptions while watching profit path.

**Step 3: Convert all editable assumptions into rows**

Render backend `editable_assumptions` as editable rows. Group by:

- revenue_driver
- standard_knob
- terminal
- other

Do not hide `other`; unknown knobs must remain visible and editable if backend declared them editable.

**Step 4: Run frontend build**

Run:

```bash
npm run build
```

Expected: pass after component wiring is complete.

---

## Task 6: Edit Mode and Preview Overlay

**Files:**
- Modify: `app/src/App.tsx`
- Modify: `app/src/styles.css`

**Step 1: Add edit state**

In the core-assumption component:

```ts
const [editMode, setEditMode] = useState(false);
const [draftValues, setDraftValues] = useState<Record<string, number | null>>({});
const [preview, setPreview] = useState<AssumptionPreview | null>(null);
const [previewLoading, setPreviewLoading] = useState(false);
const [previewError, setPreviewError] = useState<string | null>(null);
```

Draft key is the backend pointer.

**Step 2: Render editable cells**

When `editMode` is false, render normal formatted cells.

When `editMode` is true and a cell has a pointer, render a compact numeric input:

```tsx
<input
  className="assumption-cell-input"
  value={draftDisplayValue(cell)}
  onChange={(event) => updateDraft(cell.pointer, parseDraftValue(event.currentTarget.value, row.unit))}
/>
```

Percent display rule:

- Backend stores decimals for yaml1 top-level values when yaml1 already uses decimals.
- Core hypothesis `knobs` block uses percent points, but yaml1 often uses decimals.
- Therefore frontend must display based on backend `unit` and `format`, not guess from label.

If unit uncertainty exists, show number exactly as backend returns and do not multiply.

**Step 3: Debounced preview**

When draft changes, build patches:

```ts
const patches = Object.entries(draftValues).map(([pointer, value]) => ({
  pointer,
  old_value: originalValueByPointer[pointer],
  new_value: value,
}));
```

Debounce 300-500ms, then call `assumption-preview`.

If preview errors, show error banner and keep draft values visible.

**Step 4: Reset and compare**

Add buttons:

- `Edit`
- `Preview`
- `Reset`
- `Generate KA Prompt`

Show changed cells with subtle blue marker. Do not use loud colors or cards inside cards.

**Step 5: Run build**

Run:

```bash
npm run build
```

Expected: pass.

---

## Task 7: Change Brief and `/ka` Prompt Generation

**Files:**
- Modify: `src/workbench.py`
- Modify: `app/src/App.tsx`
- Test: `tests/test_workbench_assumption_editor.py`

**Step 1: Backend prompt formatter**

Add endpoint:

```python
class AssumptionBriefPayload(BaseModel):
    patches: list[AssumptionPatchPayload]
    preview_summary: dict[str, Any] | None = None


@app.post("/api/companies/{company_id}/assumption-brief")
def assumption_brief(company_id: str, payload: AssumptionBriefPayload) -> dict[str, Any]:
    company_dir = _company_dir(company_id)
    yaml1_path = _latest_yaml1(company_dir)
    core_path = _core_assumption(company_dir)
    yaml1_data = _read_yaml(yaml1_path) if yaml1_path else {}
    prompt = _format_ka_change_prompt(company_dir, core_path, yaml1_path, yaml1_data, payload)
    return {"prompt": prompt}
```

Prompt must say:

- Modify `核心假设.md`, not yaml1 directly.
- Preserve structure, historical facts, sources, and company-specific wording.
- Update both the prose section and the terminal `knobs` block.
- Then run `/comp` to regenerate yaml1 and official forecast.

**Step 2: Test prompt includes all changed knobs**

```python
def test_assumption_brief_lists_changed_revenue_driver_and_standard_knob():
    # Build payload with one income.gpm patch and one revenue driver patch.
    # Assert prompt contains labels, old values, new values, years, and canonical instruction.
```

**Step 3: Frontend modal/panel**

When user clicks `Generate KA Prompt`, call the endpoint and show a copyable prompt in a `<textarea>`.

Do not automatically edit files or run `/ka` from the web app in this phase. The agent remains the writer of canonical human-readable assumptions.

**Step 4: Verify**

Run:

```bash
py -m pytest tests/test_workbench_assumption_editor.py -q
npm run build
```

Expected: pass.

---

## Task 8: Documentation Updates

**Files:**
- Modify: `docs/数据流水线.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/前端设计规范.md`

**Step 1: Update data pipeline docs**

Add a section explaining:

```text
前端 edit mode 是 preview overlay，不是正式产物。
正式链路仍是 核心假设.md -> /comp -> yaml1 -> forecast。
```

**Step 2: Update architecture docs**

Add:

- `editable_assumptions` API
- `assumption-preview` API
- `assumption-brief` API
- no-write preview guarantee

**Step 3: Update frontend design spec**

Replace the old “收入拆分 / 关键假设 separated subtab” rule with:

- Core assumption page is a single modeling workbook.
- Revenue and all knobs share the same year axis.
- Net profit rows appear directly below total revenue.
- Unknown editable knobs must render under `其他覆盖`.

**Step 4: Run doc-adjacent verification**

Run:

```bash
rg -n "收入拆分|关键假设|assumption-preview|editable_assumptions" docs app/src src
```

Expected: docs and implementation terminology line up.

---

## Task 9: Full Verification

**Files:**
- No new files unless failures require fixes.

**Step 1: Backend tests**

Run:

```bash
py -m pytest tests/test_workbench_assumption_editor.py tests/test_yaml1_cleaner.py tests/test_forecast_pipeline.py -q
```

Expected: pass.

**Step 2: Frontend build**

Run:

```bash
npm run build
```

Expected: pass.

**Step 3: Manual workbench smoke test**

Run:

```bash
py -m src.workbench --host 127.0.0.1 --port 8765
```

Open the workbench and test `新乳业_002946`:

1. Enter core-assumption edit mode.
2. Change `低温鲜奶 · 销量 yoy` for 2025.
3. Confirm revenue and net profit preview rows change.
4. Change `整体毛利率`.
5. Confirm net profit and DCF summary change.
6. Reset changes.
7. Generate `/ka` prompt and confirm it lists both revenue-driver and standard-knob edits.

Expected: no official `Agent/forecast/` files are rewritten until `/comp` or official forecast is run.

---

## Implementation Order

1. Refactor `yaml1_cleaner` for in-memory preview.
2. Add backend editable assumption extraction.
3. Add backend preview endpoint.
4. Wire frontend types and edit mode.
5. Merge core-assumption tab layout and add net profit rows.
6. Add change brief prompt generation.
7. Update docs.
8. Run full verification.

This order gives a safe spine: preview works before the UI gets fancy, and canonical write-back remains a prompt until the user explicitly runs `/ka` and `/comp`.
