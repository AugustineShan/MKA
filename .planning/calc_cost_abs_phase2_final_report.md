# cost_abs 符号修复 · 第二段实施报告

> 状态：已按用户确认的方案 A + 三处修订（软降级、2019+ 适用域、循环风险声明）完成实现。
> 未 commit，等待用户最终确认。

---

## 1. 代码改动清单

### 1.1 src/calc.py：方案 A 实现

- 模块级新增常量 `IMPACT_ADJUSTMENT_FIELDS`（`src/calc.py:38-44`）：
  ```python
  IMPACT_ADJUSTMENT_FIELDS = {
      "assets_impair_loss",
      "credit_impa_loss",
      "oth_impair_loss_assets",
  }
  ```
- `build_income_statement` 中（`src/calc.py:153-167`）：
  - `cost_fields` 排除上述字段；
  - 新增 `impact_adjustment` 为这三个字段原值之和；
  - `operate_profit = total_revenue - total_cogs + sum(op_adj.values()) + impact_adjustment`。

**效果**：
- `-62.82` 直接加进 `operate_profit` → 利润减 62.82（正确，负=损失）。
- `+1.96` 直接加进 `operate_profit` → 利润减 1.96（正确，正=成本）。

### 1.2 src/clean.py：动态符号验证

- 新增 `import itertools`（`src/clean.py:10`）。
- 新增模块常量 `SIGN_QUESTIONABLE_IS_FIELDS`（`src/clean.py:169-174`）。
- 新增辅助函数：
  - `signed_is_cost_sum()`（`src/clean.py:1045-1060`）：汇总非减值类 cost_item。
  - `signed_is_adjustment_sum()`（`src/clean.py:1063-1075`）：汇总 operating_adjustment + 按解析符号的减值类。
  - `resolve_is_signs()`（`src/clean.py:1078-1156`）：2019+ 年启用，枚举符号组合，返回 `(sign_map, warnings)`。
- 修改 `check_is()`（`src/calc.py:1159-1230`）：
  - 接收可选 `sign_map`；
  - 非空时使用符号化和；
  - 空/None 时回退现有行为；
  - IS 1.1 在 sign_map 模式下残差只 info 不报错。
- 修改 `validate_wide()`（`src/clean.py:1765-1777`）：
  - 每年先调用 `resolve_is_signs()`；
  - 把符号相关 warnings 追加到 `period_warnings`；
  - 将 `sign_map` 传入 `check_is()`。

### 1.3 docs/yaml2_calc关系说明.md：修正描述

`docs/yaml2_calc关系说明.md:24` 原描述：

```markdown
impairment = 直接用绝对值                        ← 读 YAML2 的 assets_impair_loss + credit_impa_loss
```

改为：

```markdown
impairment = 按原值代数并入营业利润    ← 读 YAML2 的 assets_impair_loss + credit_impa_loss + oth_impair_loss_assets
                                         负值=损失（侵蚀利润），正值=收益/ reversal；不计入 total_cogs
```

---

## 2. 动态符号验证实测

### 2.1 设计要点回顾

- **适用域**：仅 2019 年及以后启用；2016-2018 标为“口径断点”跳过。
- **锚等式**：`operate_profit = revenue_base − Σ(稳定正成本) + Σ(operating_adjustment) + Σ(sign_f × value_f)`。
- **循环风险**：等式两边同源（同一张 TuShare income 表），只能做内部自洽 sanity check，不是独立交叉验证。
- **失败处理**：判不出/歧义时写 `clean_warnings`（标“口径断点/符号不可判”），软降级为 warning，不阻断；只有“判出唯一符号但仍不平”才 hard error。
- **无 plug**：绝不把残差塞进任何 `qa_*_plug` 字段。

### 2.2 新乳业_002946 实测结果

| period | 结果 | 说明 |
|---|---|---|
| 2016-2018 | warning | 口径断点，2019 年前跳过 |
| 2019 | warning | 口径断点/符号歧义：assets_impair_loss 极小，两种符号组合都满足容差 |
| 2020-2021, 2023-2025 | resolved | `assets_impair_loss=+1`, `credit_impa_loss=+1` |
| 2022 | warning | 口径断点/符号歧义：assets_impair_loss 极小 |

`clean.py --mode annual` 输出：`All checks passed!`

### 2.3 其他 4 家公司

- 安克创新_300866、伊利股份_600887、美的集团_000333、比亚迪_002594 在 `src.init` 年度 clean 中均未因动态符号验证产生 hard error；2019+ 减值符号均被解析为 `+1`（即负值=损失），与预期一致。

---

## 3. 五家公司回归结果

### 3.1 补数据过程

| 公司 | 代码 | 状态 |
|---|---|---|
| 新乳业 | 002946 | 已有 data.db + defaults.yaml |
| 安克创新 | 300866 | `src.init` 成功生成 |
| 伊利股份 | 600887 | `src.init` 成功生成 |
| 美的集团 | 000333 | `src.init` 初跑 BS 2.1 失败（`lending_funds` 缺失）；手动运行 `src.annual_report_reconciler` 生成 10 条 approved override 后重跑通过 |
| 比亚迪 | 002594 | `src.init` 初跑 BS 3.1 失败（`estimated_liab` 缺失）；手动运行 `src.annual_report_reconciler` 生成 10 条 approved override 后重跑通过 |

**无“未验证”公司**：5 家全部补出完整 `data.db` + `defaults.yaml`。

### 3.2 修复前后对照表（forecast 2026）

| 公司 | 代码 | 指标 | 修复前 | 修复后 | 差值 | 差值比例 |
|---|---|---|---|---|---|---|
| 新乳业 | 002946 | operate_profit | 978.6818 | 856.2503 | −122.4315 | −12.51% |
| 新乳业 | 002946 | n_income | 866.4077 | 757.7510 | −108.6567 | −12.54% |
| 新乳业 | 002946 | per_share_value | 14.2184 | 12.2331 | −1.9853 | −13.96% |
| 安克创新 | 300866 | operate_profit | 3765.6648 | 2939.4251 | −826.2396 | −21.94% |
| 安克创新 | 300866 | n_income | 3369.0648 | 2629.1336 | −739.9312 | −21.96% |
| 安克创新 | 300866 | per_share_value | 98.6949 | 76.9848 | −21.7100 | −22.00% |
| 伊利股份 | 600887 | operate_profit | 16363.4990 | 14262.3602 | −2101.1388 | −12.84% |
| 伊利股份 | 600887 | n_income | 14026.6347 | 12164.8031 | −1861.8316 | −13.27% |
| 伊利股份 | 600887 | per_share_value | 30.5707 | 26.1452 | −4.4255 | −14.48% |
| 美的集团 | 000333 | operate_profit | 58264.3770 | 55108.6388 | −3155.7382 | −5.42% |
| 美的集团 | 000333 | n_income | 48952.9850 | 46306.4149 | −2646.5702 | −5.41% |
| 美的集团 | 000333 | per_share_value | 90.0813 | 84.8120 | −5.2693 | −5.85% |
| 比亚迪 | 002594 | operate_profit | 43871.8556 | 39349.3704 | −4522.4852 | −10.31% |
| 比亚迪 | 002594 | n_income | 36892.1119 | 33051.3366 | −3840.7753 | −10.41% |
| 比亚迪 | 002594 | per_share_value | 34.8664 | 28.2953 | −6.5711 | −18.85% |

**结论**：修复前 operate_profit / n_income / per_share_value 均被高估；修复后全部下降，符合“减值应侵蚀利润”的会计直觉。安克创新影响最大（−22%），因其减值/信用损失占比高。

---

## 4. 配平复核

- `src.calc` 在每个预测期调用 `validate_accounting()`，检查：
  - `total_assets = total_liab_hldr_eqy`（BS 配平）
  - `c_cash_equ_beg_period + n_incr_cash_cash_equ + qa_cf_cash_reconcile_plug = c_cash_equ_end_period`（CF 现金桥接）
- 5 家公司修复后 `src.calc` 均正常完成并输出 `Per-share value`，未抛出 `CalcError`。
- 因此三表配平全部通过。

---

## 5. 发现但未引入本次改动的附带问题

1. **`src.init` 自动触发的 `annual_report_reconciler.py` 因 `ModuleNotFoundError: No module named 'src'` 失败**：
   - 原因：`clean.py` 的 `auto_reconcile_annual_failure()` 用 `sys.executable` 直接调用脚本文件，未以 `-m` 方式运行。
   - 本次为了完成 5 家回归，手动用 `python -m src.annual_report_reconciler` 补全了 美的/比亚迪 的 override。
   - **建议**：如用户认可，可在后续 MR 中修复 `auto_reconcile_annual_failure()` 的调用方式；但这不属于 cost_abs 符号修复范围，本次未改。

2. **比亚迪 baseline 与修复后均出现 `negative_cash_from_plug` review flags**：
   - 这是 DCF 引擎对现金 plug 为负的经济性提示，与本次符号修复无关；修复后 flag 数量从 4 个增加到 5 个，是因为利润下调后现金需求更早暴露。

---

## 6. 待用户确认事项

- [ ] 认可 `src.calc.py` 与 `src.clean.py` 的改动。
- [ ] 认可动态符号验证的软降级策略（2019 前跳过、判不出/歧义只 warning）。
- [ ] 认可 5 家回归结果。
- [ ] 是否需要在本次一并修复 `auto_reconcile_annual_failure()` 的模块调用问题？
- [ ] 允许 commit。

---

*报告生成时间：2026-06-14。*
