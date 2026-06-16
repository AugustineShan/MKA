# YAML1 Template Contract Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make yaml1 revenue templates executable and auditable without expanding `calc.py` beyond its existing `model.revenue_yoy` and `income.gpm` inputs.

**Architecture:** Keep the deterministic cleaner as the contract boundary. The compiler skill may only emit finite, stateless templates that fold directly into existing YAML2 paths; formula/DAG shapes remain explicitly unsupported until a separate evaluator is designed.

**Tech Stack:** Python cleaner/tests, Markdown skill docs, existing workbench YAML display helpers.

---

### Task 1: Seal The Skill Contract

**Files:**
- Modify: `skills/yaml1compiler_v4 (2).md`
- Modify: `skills/核心假设生成修改器_skill_v17.md`

**Steps:**
1. Update the compiler skill to declare executable revenue families as `factor_product`, `vol_price` compatibility alias, `vol_price_margin` compatibility alias, `growth`, and `abs`.
2. Mark `formula`, `bridge`, `ratio_to_driver`, cross-period recursion, reusable intermediate variables, and general DAG as not implemented and not generatable.
3. Define `factor_product` as an n-factor product with per-factor `projection.kind` of `yoy`, `abs`, or `constant`.
4. State the over-determined rules: `decomposition_sum` and future `mix_allocation` are mutually exclusive per node; leaf margins and top-level `income.gpm` are mutually exclusive.
5. Update the v17 generator skill to say company skeletons may vary, but compiler-executable algorithm templates are finite.

### Task 2: Add Cleaner Test Coverage

**Files:**
- Modify: `tests/test_yaml1_cleaner.py`

**Steps:**
1. Add synthetic unit tests for `factor_product` with two factors and three factors.
2. Add an `abs` family test using `knobs.revenue_abs`.
3. Add a nested `decomposition` test.
4. Add a margin-fold test proving leaf margins derive `income.gpm`.
5. Add hard-error tests for partial margins, leaf margins plus top-level `income.gpm`, and unsupported `formula`.

### Task 3: Implement Cleaner Templates

**Files:**
- Modify: `src/yaml1_cleaner.py`

**Steps:**
1. Extend `FoldResult` with optional `gpm_values`.
2. Replace direct segment iteration with recursive `decomposition_sum` folding.
3. Implement stateless leaf evaluators for `factor_product`, `vol_price`, `vol_price_margin`, `growth`, and `abs`.
4. Add factor projection evaluation for `yoy`, `abs`, and `constant`.
5. Add margin-fold derivation and over-determined checks.
6. Inject derived `income.gpm` into overlay only when all revenue leaves provide margins and no top-level `income.gpm` knob is present.
7. Improve unsupported family/kind errors so `formula` tells the agent it is not implemented.

### Task 4: Update Workbench Display

**Files:**
- Modify: `src/workbench.py`

**Steps:**
1. Reuse the same stateless revenue evaluation semantics for YAML1 breakdown display.
2. Traverse nested decomposition leaves.
3. Show factor rows for `factor_product`, legacy knob rows for compatibility families, and `revenue_abs` rows for `abs`.

### Task 5: Update Pipeline Documentation

**Files:**
- Modify: `docs/数据流水线.md`

**Steps:**
1. Replace the old direct-segment revenue folding description with recursive `decomposition_sum`.
2. Document executable leaf families and their fold targets.
3. Document margin-fold and over-determined rules.
4. State that formula/DAG is not currently executable.

### Task 6: Verify

**Commands:**
1. `pytest tests/test_yaml1_cleaner.py -q`
2. If practical, run the existing forecast path for the New Hope Dairy yaml1 sample.

**Expected:** Existing New Hope Dairy tests still pass; new synthetic template tests pass; no `calc.py` change required.
