# 财务费用细则升级计划

> 状态：已实现，测试通过（54/54）  
> 关联模块：`src/financial_expense_analyzer.py`、`src/defaults_gen.py`、`src/init.py`、`src/annual_report_utils.py`

---

## 1. 要解决什么问题

### 1.1 现状

MKA 的 `defaults.yaml` 是 YAML2 机器平推底座，其中 `income.financial_expense` 决定 DCF 引擎如何循环求解财务费用：

```yaml
income:
  financial_expense:
    interest_mode: circular_average_balance
    interest_expense_rate: ...      # 利息支出 / 平均有息负债
    cash_interest_rate: ...         # 利息收入 / 平均货币资金
    other_fin_exp_abs: ...          # 不随余额变动的非利息项
```

`calc.py` 预测时不是平推历史 `fin_exp` 绝对值，而是：

```
fin_exp = avg_debt × interest_expense_rate − avg_cash × cash_interest_rate + other_fin_exp_abs
```

因此利率类参数的准确度直接决定预测质量。

### 1.2 当前缺陷

`defaults_gen.py` 目前从 `clean_annual` 机械抽取：

- `interest_expense_rate = fin_exp_int_exp / debt`
- `cash_interest_rate = fin_exp_int_inc / cash`
- `other_fin_exp_abs = fin_exp − fin_exp_int_exp + fin_exp_int_inc`

问题在于：

1. **TuShare 只给净值和几个粗粒度原子**。`fin_exp_int_exp` / `fin_exp_int_inc` 的口径因公司/审计师而异，可能已经把资本化利息、财政贴息等净了进去。
2. **年报附注里有更细的财务费用明细**，但当前没有利用。这导致利率分子可能被资本化利息、财政贴息等政策项系统性压低或抬高。
3. **总额勾稽无法发现边界错误**。只要 `interest − interest_income + other = fin_exp`，总额就过；但"利息 ↔ 其他"的边界错会直接影响利率，而总额看不出来。

### 1.3 目标

新增"财务费用细则生成器"，让 `init` 流程在 clean 之后自动：

- 从年报 Markdown 切片"财务费用"附注
- 用 LLM 拆出：借款利息、资本化利息、财政贴息、利息收入、汇兑损益、手续费等
- 按**固定规则**重算利率类参数
- 生成审计级 evidence 到 `recon/`
- `defaults_gen.py` 读取 evidence 并合并进 `defaults.yaml`

最终提高 YAML2 财务费用结构的准确度，且全程可追溯、可回落。

---

## 2. 要做什么

### 2.1 新增模块：`src/financial_expense_analyzer.py`

职责：只产 evidence，不写 `defaults.yaml`。

公共 API：

```python
def analyze(ticker: str, db_path: Path | None = None, company_dir: Path | None = None, force: bool = False) -> Path
def default_evidence_path(company_dir: Path) -> Path
def load_evidence(company_dir: Path) -> dict[str, Any] | None
```

处理流程：

1. 读 `data.db` 最新 `clean_annual` 行，取 anchor：`fin_exp`、`fin_exp_int_exp`、`fin_exp_int_inc`、有息负债、货币资金
2. 按 base_period → 年报文件映射，找到对应年报 Markdown
3. 切片"财务费用"附注
4. 调 LLM 返回带标签分项：
   - `interest_expense_gross`：银行/租赁/债券利息支出
   - `capitalized_interest`：资本化利息
   - `interest_subsidy`：财政贴息冲减
   - `interest_income`：利息收入
   - `other_non_interest`：汇兑损益、手续费、其他财务费用
5. 按固定规则 derive：
   - `interest_expense = interest_expense_gross − capitalized_interest`
   - `interest_income = interest_income`
   - `other_fin_exp_abs = fin_exp − interest_expense + interest_income`
6. 两道勾稽：
   - **总额勾稽**：`interest_expense − interest_income + other_fin_exp_abs ≈ fin_exp`
   - **边界勾稽**：动态 detect clean 的 `fin_exp_int_exp` 实际对应哪种口径，验证 LLM 分项能重建 clean 原子
7. 写 evidence 到 `companies/{公司}/recon/financial_expense_detail_latest.json`

### 2.2 修改 `src/defaults_gen.py`

在 `build_defaults()` 中：

1. 先按现有逻辑算 mechanical 值
2. 尝试加载 `recon/financial_expense_detail_latest.json`
3. 若 evidence 满足 `status == approved`、`confidence == high`、勾稽全过、base_period 匹配：
   - 覆盖 `interest_expense_rate`、`cash_interest_rate`、`other_fin_exp_abs`
   - 同步覆盖 `base_interest_expense`、`base_interest_income`（避免半覆盖）
   - `source` 改为 `annual_report.fin_exp_note`
4. 否则保持 mechanical 值，`source` 保持 `clean_annual.*`

### 2.3 修改 `src/init.py`

在 `stage_clean()` 之后新增 `stage_financial_expense()`：

- 只在 clean 成功后运行
- 幂等：evidence 存在且非 `--force` 则跳过
- 失败（LLM 超时、低 confidence 等）只 warning，不影响后续流程
- 把状态写进数据拉取报告

### 2.4 抽公共模块：`src/annual_report_utils.py`

把 `annual_report_reconciler.py` 中可复用的部分抽出：

- `.env` 加载、provider/model/timeout 配置
- `parse_ticker()`、`find_company_dir()`、`default_db_path()`
- 年报 Markdown 切片：`annual_markdown_path()`、`read_md_lines()`、`find_line()`、`compact_window()`
- LLM 调用：`call_llm()`

`annual_report_reconciler.py` 改 import，`financial_expense_analyzer.py` 也 import 它。

### 2.5 回归测试

在 `tests/` 新增测试：

- `test_financial_expense_analyzer.py`：用新乳业真实数据断言
  - 财政贴息 ≈ 3.82 百万元
  - 利率分子 `interest_expense = gross − capitalized`（不含贴息）
  - `other_fin_exp_abs` 包含贴息效果（为负，因贴息冲减费用）
  - `detected_basis == "net_of_capitalized_and_subsidy"`
  - evidence `status == approved`

---

## 3. 设计决策

| 决策 | 选择 | 原因 |
|------|------|------|
| 利率分子 | `gross − capitalized` | 只保留随债务余额变动的真利息；资本化没进 P&L，剔除；贴息是外生政策项，不进利率 |
| 贴息去向 | `other_fin_exp_abs` | 外生补贴，不随债×市场利率增长；引擎预测时当常数 |
| cross_check | 动态 detect clean 口径 | 不假设所有公司都像新乳一样把贴息净进利息；换公司不会崩 |
| init 职责 | 只写 evidence | YAML2 所有权归 `defaults_gen.py`，不能裂 |
| 失败策略 | warning + 回落机械值 | 这是增强不是 clean 那种事实地基，不能崩管线 |
| 覆盖一致性 | base + rate 一起动 | 防止"base 106、rate 按 97"这种自相矛盾 |

---

## 4. 已发现的坑

### 4.1 年报期间映射 off-by-one

`base_period` 是 FY N，但年报文件命名是发布年份 N+1。

- 例：`base_period = 2024` 对应 `2025_年度报告.md`
- 在该报告里，FY2024 数据在**上期发生额**列，不是本期
- 读错列会导致 fin_exp 完全对不上（新乳 2025 报告"本期"77.77 vs "上期"100.96）

**处理**：实现时先按 `base_period + 1` 找文件，读"上期"；同时用 frontmatter/文件名二次确认。

### 4.2 clean 口径不统一

实测新乳：`clean.fin_exp_int_exp = 106.27 = gross − capitalized − subsidy`。

但不同公司/不同审计师可能：

- 只净资本化：`clean = gross − capitalized`
- 都不净：`clean = gross`
- 只净贴息：`clean = gross − subsidy`

**处理**：cross_check 不硬编码，而是从 LLM 分项重建四种候选口径，选最接近 clean 实际值的那种 detect。

### 4.3 总额勾稽藏边界错误

只要 `interest − interest_income + other = fin_exp`，总额就平。但把贴息错放进利率分子，总额仍然平，只是利率被系统性压低。

**处理**：

- 固定利率分子 `gross − capitalized`
- 加第二道边界勾稽：detect clean 口径
- 贴息必须显式落在 `other_fin_exp_abs` 里

### 4.4 other 异常阈值分母会爆

用 `other / max(abs(fin_exp), 1.0)` 时，现金多的公司 `fin_exp` 接近 0，分母被夹成 1，比率误报"异常大"。

**处理**：只在 `abs(fin_exp) > 10` 百万元时看 `other / fin_exp`；同时用 `other / revenue` 作为辅助信号。

### 4.5 base / rate 不能半覆盖

如果 `interest_expense_rate` 用 LLM 值而 `base_interest_expense` 仍用 clean 值，会出现 base 和 rate 口径不一致。

**处理**：approved 时，`base_interest_expense`、`base_interest_income`、`interest_expense_rate`、`cash_interest_rate`、`other_fin_exp_abs` 一起覆盖。

### 4.6 LLM 可能超时/无 key

环境默认 Kimi 但可能无 key；GLM 也可能未配置。

**处理**：

- 复用 reconciler 的 `.env` 读取逻辑
- LLM 失败时 graceful fallback，写 fallback evidence，不降管线

---

## 5. 验收标准

1. 管线绿、配置合法
2. `defaults.yaml` 的 `source` 能区分 `clean_annual.*` vs `annual_report.fin_exp_note`
3. 新乳回归用例通过：贴息 ≈ 3.82M 进 other、利率分子不含贴息
4. 无 evidence 或 fallback 时，干净回落到 mechanical 值
5. 全量测试 `pytest tests/` 通过

---

## 6. 下一步

确认本计划后，按以下顺序实现：

1. `src/annual_report_utils.py`
2. `src/financial_expense_analyzer.py`
3. 改 `src/annual_report_reconciler.py` import
4. 改 `src/defaults_gen.py`
5. 改 `src/init.py`
6. 补测试 + 跑回归
