# TECHHEAD.md — Tech Head 操作记忆

> 这是我（Claude，作为本项目 tech head）的私有工作笔记，记录我对项目的真实判断、状态认知、未决策点与纪律。
> 与 `docs/ARCHITECTURE.md`（代码现状）和 `docs/理解层_设计决策与开发方向.md`（设计意图）互补：
> 那两份是对外契约，本文是我的内部判断和待办。**每次形成新判断或状态变化时更新本文。**
> 维护者视角：诚实优先，不粉饰红线。

---

## 1. 一句话定位（我的理解）

MKA 本质是一个**买方投研工作台的骨架**：把 A 股公司"一堆投研材料 → 一份能喂给 DCF 引擎的判断覆盖层"这条链工程化。
卖方工具（Wind AI / Bloomberg AI）产标准化对外结论；本项目要沉淀"分析师对每家公司的私有判断"。
**差异点 = "yaml2 机器平推底座 + yaml1 人的判断覆盖层 = DCF 估值"** 这个双层模型。

新乳业实测：yaml1 估值 15.71 vs yaml2 平推 12.23，差额 3.48 就是"老板这套判断的价值"——这是产品命题的具象证明。

---

## 2. 架构分层（数据流，我的心智图）

```
阶段① data_fetcher.py   TuShare → 标准化(单位/去重/镜像) → SQLite raw_tushare
阶段② clean.py          raw_tushare(EAV) → 宽表 → 严格配平校验 → clean_annual/clean_quarterly
   └ 缺口补全 annual_report_reconciler.py（年报 Markdown + LLM，唯一事实层判断注入口，审计严）
增强  financial_expense_analyzer.py  年报附注 → financial_expense.yaml（财务费用真实拆分）
YAML2 defaults_gen.py    clean_annual → defaults.yaml（完整、配平、无判断的平推底座）
语义  核心假设.md         投研材料 → 盈利模型底稿（认/搬/议；LLM 产，只产 md）
翻译  compiler(skill)     核心假设.md + defaults.yaml + 字典 → yaml1*.yaml（稀疏判断覆盖层）
清洗  yaml1_cleaner.py    yaml1 + defaults → fold/expand/resolve/backtest → .modelking/forecast_params.yaml
  └ formula 层 yaml1_formula.py（受限 DAG 求值器，长尾算法用，默认关）
算账  calc.py             forecast_params → IS→BS→CF→DCF（纯算账核，永远看不到 yaml1）
编排  forecast.py         正式入口：py -m src.forecast --ticker XXX → forecast/
前端  workbench.py + app/ 本地只读工作台 + 一键重算 + DCF sensitivity 滑块
```

**铁律（不可破）**：
- LLM 当翻译，Python 当执行器。
- calc.py 只吃清洗后的标准参数（`--forecast-params`），永不见 yaml1/defaults/formula。
- 绝不 hardcode 科目清单；能力边界 = 真实文件边界（现查字典 `数据格式参考.md`）。
- raw_tushare 永不被修改；补数只进年度 clean 宽表 + 审计表。
- 一个事实只能有一个来源（over-determined 硬失败）。
- 绝不静默降级：缺值不补 0、缺 seed 不猜、回测不过不放行。
- 项目第一原则：`target_gt_calc`（合计>明细，TuShare 漏披露）→ reconciler 去年报补全，不是放弃/人工。

---

## 3. 当前真实状态（诚实记录 · 2026-06-16）

### 健康度：测试套件是红的
`python -m pytest tests/` → **77 passed / 6 failed**（分支 `refactor/organize-root-directory`）。

| 失败测试 | 性质判断 | 优先级 |
|---|---|---|
| `test_yaml1_cleaner::test_fold_revenue_uses_structured_unit_factor_and_clean_anchor` | KeyError `low_temp_fresh_milk`，疑似 fixture/segment 命名漂移 | 需查 |
| `test_yaml1_cleaner::test_clean_yaml1_expands_fade_hold...` | forecast_years 10 vs 期望 12，疑似 horizon 口径变更未同步测试 | 需查 |
| `test_forecast_pipeline::...rebuilds_forecast` | per_share_value golden 值漂移（16.81 不匹配），引擎变更未更新黄金值 OR 真回归 | **需查（可能掩盖真 bug）** |
| `test_financial_expense_analyzer`（×3） | `status=='error'`，疑似 LLM 调用在测试环境失败（无 key/网络/未 mock） | 测试环境问题，需隔离 |

**关键洞察**：前两个失败在 **HEAD 上就已存在**（不是当前 WIP 引入）。即这条分支**提交时就带着红测试**。

### WIP 状态（未提交工作树）
- `src/yaml1_formula.py`（583 行，新增）+ `tests/test_yaml1_formula.py`（163 行，新增）：formula DAG 求值器，**7 个 formula 测试全绿**。
- `src/yaml1_cleaner.py` / `tests/test_yaml1_cleaner.py`：接入 formula。
- 6 份 docs/skills 同步修改（契约文档、compiler skill、数据流水线）。

### 文档 vs 现实的分歧（契约漂移，已修正 2026-06-16）
- ~~`docs/formula_DAG开发文档.md` 写"状态：已上线"~~ → 已降级为"**实验性·受限**"，并写明升稳定的硬条件（②真实异构公司全程跑通，未达成）。
- ~~`docs/理解层_设计决策...md` 第 9 节仍把 formula 标"延后/留槽/一行没写"~~ → 已更新为"已落地但实验性"，三件事中 schema/求值层已建、compiler 分支已同步 skill，剩真公司验证。
- `docs/ARCHITECTURE.md` 契约表 formula 行 + 变更日志已同步为"实验性·受限"。
- **三份文档现已一致**：formula = 代码闭环 + 单测绿，但仅合成 fixture 验证、真公司未验泛化。"已上线"过度声明已清除。

---

## 4. 关键风险 / 技术债（我的清单）

1. **红测试基线**（最高优先）：一个核心命题是"hard check 绝不静默放行"的项目，自身测试套件却带 6 红。可信度地基松动。必须先回绿，再谈新功能。
2. **golden-value 测试脆弱**：forecast_pipeline 用硬编码 per_share_value 断言。引擎一改就红，且无法区分"故意变更"和"真回归"。需要更稳健的断言策略（配平恒等式 + 区间，而非精确点值）。
3. **LLM 依赖测试未隔离**：financial_expense_analyzer 测试真打 LLM，环境无 key 即红。CI/本地不可复现。需 mock LLM 边界。
4. **WIP 长期不提交**：formula 这轮改动跨 8 文件 + 2 新文件，越拖越难收口，且文档已抢跑声明"上线"。
5. **公司目录契约靠纪律维持**：forecast/ 必须先清空再生成、不许 yaml2_yearly.yaml 顶层等，目前靠文档约定 + 测试断言，无运行时强约束。
6. **分支状态**：当前在 `refactor/organize-root-directory`，混着 refactor + formula 功能 + docs，关注点不单一。

---

## 5. 待与老板对齐的决策点（开放问题）

> 这些是我作为 tech head 想和你一起在"落地文档和需求"层面拍板的，不是细节。

- **A. formula/DAG 到底算不算"上线"？** ✅ 已定（2026-06-16）：降级为"**实验性·受限**"。收口标准写进 formula 文档：①测试全绿（已达成）+ ②第二家异构公司从 compiler→cleaner→calc→回测全程跑通（**未达成**）才升"稳定"。三份文档已同步。
- **B. 红测试的处理顺序**：先回绿基线（我建议），还是先收口 formula WIP？两者有交叉。
- **C. golden 值测试策略**：是否同意把"精确 per_share 断言"改成"配平恒等式 + 合理区间"？这是测试哲学层面的决定。
- **D. 下一家验证公司**：设计文档说"第二家异构公司验泛化是最有价值的下一战"。选谁（伊利/安克/茅台基酒链）？这决定 formula 是否真被逼出来。
- **E. 工作台路线**：第一版只读 + 重算已成。下一步是只读增强，还是开始碰"可编辑 yaml1 / 投研版 git"（设计文档第 7、8 节，尚未定论）？

---

## 6. 我的工作纪律（self-discipline）

- 改数据流水线 → 必须同步 `docs/数据流水线.md` + `docs/ARCHITECTURE.md` 变更日志。
- 不在中文目录写中间产物；不靠 print 调试中文（落盘 + Read）。
- 系统全局 Python（`/c/Users/.../Python311`），不碰 venv，pip 走清华镜像。
- 功能分支作业，小步提交，提交前 `git diff` review。
- 不声明"上线/稳定"除非测试绿 + 验证样本通过。诚实上报失败。

---

## 7. 进度日志

- **2026-06-16**：首次通盘 review。建立本文。
  - 确认架构愿景（双层买方工作台）与代码现状基本对齐。
  - 发现：全套测试 77/6（红基线，2 个失败在 HEAD 已存在）；formula WIP 测试自身绿但全局未回绿；formula 文档"已上线"声明与现实/设计文档存在分歧。
  - 结论：当前不应推进新功能，应先（1）回绿基线（2）收口或明确降级 formula WIP 状态（3）和老板对齐第 5 节决策点。

- **2026-06-16（回绿基线，完成）**：6 个红测试全部修复，`pytest tests/` → **83 passed / 0 failed**。
  - **根因（确定）**：`test_yaml1_cleaner`(2)、`test_forecast_pipeline`(1)、`test_financial_expense_analyzer`(3) 全都 `glob("companies/*_002946")` 直接吃**活的、gitignore 的运行时数据**。golden 值校准于 06-15 状态；之后 yaml1 被重编译（`yaml1_新乳业_20260616.yaml`：分部更名 low_temp_*→fresh_milk 等、horizon 12→10 年）、data.db 含 FY2024，导致全部漂移。**不是引擎回归**——forecast 跑通、backtest passed、三表配平。
  - **修法（老板拍板：冻结 fixture + 不变式）**：
    - 新增 `tests/fixtures/company_002946/`（data.db VACUUM 后 2.21M + defaults.yaml + yaml1 + 合成 `annuals/2025_年度报告.md` 财务费用附注桩）。**committed 的不可变快照**，永久去耦合。
    - `tests/conftest.py` 加 `copy_fixture_company()` 共享 helper。
    - `test_yaml1_cleaner`：`company_dir()` 指向 fixture；两个 golden 测试的值从冻结数据**实跑重派生**（非猜）；fade 警告"总增速低于永续/末年增速<永续"仍触发，测试意图保留。
    - `test_financial_expense_analyzer`：delegate 到 fixture；mock 分项与期望值**本就校准于 FY2024、无需改**（124.15−14.06−3.82=106.27=fin_exp_int_exp），唯一缺的是 2025 年报 markdown，由 fixture 桩补上。
    - `test_forecast_pipeline`：per_share 点断言 → **不变式**（finite + 1<x<200 + 逐年 BS 配平 residual<1 + backtest passed + yaml1 命名无关断言）。
  - **遗留风险（已记，未在本轮处理）**：
    - `tests/test_clean.py:192` 同类活数据耦合（`glob("companies/*_688775")`），当前绿（该公司数据在），但同样脆。下次碰 clean 测试时一并冻结。
    - **financial_expense 生产侧数据新鲜度**：现实中 新乳业 annuals 只到 FY2024，缺 2025 年报；按设计 base_period N→报告 N+1 读上期列，故**最新财年在下一年年报下载前无法分析**（`analyze()` 取 max period 会 error）。这是数据新鲜度问题（需补下 2025 年报），非代码 bug，但 `init`/analyzer 对最新年会报 error，**值得产品层决定**：是否让 analyze() 跳到"最近有 N+1 年报的财年"、或对缺 N+1 优雅降级而非 error。
  - **状态**：基线已绿且去耦合。fixture data.db 未被 gitignore，`git add` 即纳入。**尚未 commit**（等老板确认）。
  - **下一步建议**：(1) commit 本轮（仅 tests/ + fixtures + techhead.md）；(2) 回到 §5：formula WIP 收口/降级声明 + 方向决策点。

- **2026-06-16（合并收拢 + formula 状态校正，完成）**：
  - 仓库收拢：`refactor/organize-root-directory` fast-forward 合并到 main，删本地+远端所有分支，只剩 main；83 测试绿；顺手修 `.gitignore` 的 `annuals/` 规则会漏 fixture 桩的问题（加精确 negation）。
  - **formula 状态声明改诚实（§5-A 落地）**：三份文档此前互相矛盾——`formula_DAG开发文档.md` + `ARCHITECTURE.md` 过度声明"已上线/稳定"，`理解层_设计决策 (6).md` 却仍停在"延后/一行没写"（反向陈旧）。统一校正为"**实验性·受限**"：代码闭环 + 单测绿已达成，但仅合成 fixture 验证、真公司未验泛化。写明升"稳定"的硬条件（②第二家异构公司全程跑通）。`yaml1算法模板契约.md` 本就措辞克制（"已有受限执行器"），未改。
  - **状态**：文档与现实一致；§5-A 关闭。下一个最有价值的开放点 = §5-D（选第二家异构公司，真正逼出/检验 formula 泛化）——等老板拍板。
</content>
</invoke>
