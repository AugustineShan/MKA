# /init 技能文档

> 一键把一个 A 股公司跑完 MKA 取数 + 校验全流水线。Agent 只负责输入解析兜底、读退出码、如实汇报；所有确定性编排由 `init.py` 完成。
>
> 真源：`.claude/skills/init/SKILL.md`（技能行为以该文件最新版为准，本文档是它的展开说明）。

## 一、定位

`python -m src.init <公司>` 把一个公司跑完 MKA 全流程：取数 → 年报下载 → 清洗配平校验 →（必要时）年报确认补全后重跑 → 生成年度核心指标速览 + 财务费用细则 + defaults.yaml。

Agent 只做：输入解析兜底、读退出码、如实汇报。不手敲 `annual_report_reconciler.py`，不静默改判成功。

**输入形态**（原样传入，脚本自解析）：
- 完整 ticker：`000333.SZ`
- 裸代码：`000333`（自动补后缀）
- 中文公司名：`美的集团`（TuShare stock_basic 解析）
- 批量：`python -m src.init 000333.SZ 600519.SH 美的集团`

**常用 flag**：`--force`（全量重拉）、`--mode annual|quarterly|all`（默认 all）、`--no-markdown` / `--force-markdown`。

**幂等**：默认增量——当日已拉取跳过取数，已存在年报 PDF/MD 跳过下载，年报补数只在重跑时应用。反复 init 同一公司廉价，用于日常更新。

---

## 二、6 阶段流水线

### 阶段① 取数 `stage_fetch`

TuShare Pro 拉三表（income / balancesheet / cashflow）+ daily_basic → 标准化单位 → 入库 `Agent/data.db`。

- 限速 0.8s/次（约 75 次/分，低于中转站 100 次/分）；限频错误等 60s 重试，最多 3 次；鉴权/权限错误直接抛出不重试。
- **去重规则**（同一 end_date 多条）：`report_type='1'` → `comp_type='1'` → `update_flag='1'` → `f_ann_date` 最晚 → `ann_date` 最晚。
- **入库健康检查（硬校验，不过拒绝入库）**：三表各有记录；主键无重复；ticker 一致；每端点每报告期覆盖官方全部数值字段（income=86 / balancesheet=150 / cashflow=89 ×期数）；最新年度核心字段不缺（revenue, n_income_attr_p, total_assets, total_liab, total_hldr_eqy_inc_min_int, n_cashflow_act）；meta 含 ticker/name/latest_trade_date/total_share/total_mv；BS 配平 total_assets≈total_liab+权益（容差 0.01）；CF 勾稽 CFO+CFI+CFF+汇兑≈现金净增（0.01）；季度加总 Q1+Q2+Q3+Q4=年报（0.01）。
- `--force` 清空旧 raw_tushare 重拉。

### 阶段② 年报/季报下载 + 业务拆分抽取（后台线程，与首轮 clean 并行）

- `stage_reports`：复用 `vendor/use_cninfo`，下载年报 PDF + Markdown 到 `公告/年报/`（`{年份}_年度报告.pdf` / `.md`，修订版 `_修订版`），季报按需；只保留"YYYY年年度报告"+修订版，排除摘要/英文版；按年份新→旧、同年修订版优先；已存在分别跳过；cninfo 请求/下载间隔 1-2 秒。
- `stage_business_breakdown`：从年报 Markdown 抽取**官方营收/成本拆分** → `Agent/OfficialBreakdowns/`，6 个文件：
  - `business_revenue_breakdown.csv` / `.jsonl`（年度）
  - `business_revenue_breakdown_h1.csv` / `.jsonl`（近 3 年半年报）
  - `business_revenue_breakdown_all.csv` / `.jsonl`（合并）
  - 抽取维度（`dimension` 列区分）：`industry`/`product`/`region`/`sales_model` 四维营收+成本+毛利率+同比（主表）；`volume` 产销量（生产量/销售量/库存量 + 三项同比，带物理单位）；`cost_composition` 成本构成（分部×成本项：直接材料/直接人工/制造费用… + 本期金额/占比/上年/上年占比/变动）。`volume`/`cost_composition` 是"收入和成本分析"同节的另两张表，由专用解析器处理；分部只写一次时（会稽山式）按继承归位，每行都写时（青岛啤酒式）按行拆。`分部间抵消`行自动过滤。
- `--no-markdown` 跳过 Markdown，连带跳过业务拆分。

> **注意**：`OfficialBreakdowns` 是年报原文披露的官方营收拆分明细（事实抽取），给 `/ka`、`/brkd` 当素材；**不是建模层业务拆分**（分业务线收入×毛利率×驱动因子假设、写进 `核心假设.md`），后者是 `/brkd` + `/ka` 的职责，init 只备齐数据与素材。

### 阶段③ clean 配平校验 `stage_clean`（同进程调 `clean_all()`）

EAV → 透视宽表 → 严格配平校验 → 写 `clean_annual` / `clean_quarterly`（325 官方字段 + 6 QA plug）。

- **硬校验**（CheckError 报错停止）：IS 1.1-1.6、BS 2.1-4.3、CF 5.1-5.5、IS 补充 6.1-6.3、跨表 7.1、逐年连续性 7.4。季度 BS bucket 小计残差和 CF 5.5 现金桥接残差先进显式 QA plug + warning，plug 后仍不平才停。
- **软校验**（仅 warning）：跨表 7.2-7.3、方向合理性 10.1、量级 10.2、折旧vs固定资产 10.3、毛利率范围 10.4。
- 容差 < 1（百万元）。
- **IS 1.2 optional 调整项 + NULL provenance**：`oth_income`/`credit_impa_loss`/`asset_disp_income` 等 optional 调整项 TuShare 对部分公司全年返回 NULL，`fillna(0)` 会静默吞掉缺口。规则：`pivot_to_wide` 在 fillna 前捕获 NULL 字段集（存 `wide.attrs["null_fields_by_period"]`）；`missing_optional_is_adjustments` 只放行"raw 非 NULL 且值≈0"的字段、排除 NULL；残差>0 且存在 NULL optional 时 IS 1.2 硬失败进 reconciler 闭环。
- **合并科目 resolve 规则**：`accounts_receiv_bill`、`oth_rcv_total`、`fix_assets_total`、`cip_total`、`accounts_pay`、`oth_pay_total`、`long_pay_total` 等自动适配合并/拆分项。
- **两道年份闸门**：
  - **2010 闸门**（`clean.RECONCILE_MIN_YEAR=2010`）：2010 前年度硬失败降级 warning 直接入库，不阻塞、不触发 reconciler。原因：A 股 2010 前披露稀疏。
  - **pre-IPO 闸门**（`clean.earliest_annual_md_year`）：上市前年份（早于本地最早年报 Markdown 年份）硬失败同样降级 warning 入库——上市前 TuShare 数据源自招股书、cninfo 无该年年报 MD，reconciler 无 MD 可核对。`init.py` 在年报下载完成后重跑一次 clean 让闸门生效，pre-IPO 年由此通过、不触发 reconciler。无年报 MD 时闸门关闭。

### 阶段④ 年报补全重跑（仅年度硬失败时触发）

年度硬校验失败 → 自动触发 `annual_report_reconciler`（强触发，agent 无需手敲）。

- **两轮补数**（`MAX_BACKFILL_CYCLES=2`）：
  1. 第一轮：clean 失败 → 强触发 reconciler 提议 override。
  2. 第二轮：reconciler 在 collect_failures 前先应用第一轮 approved override，专攻更小残差。
- **LLM**：GLM `glm-5.2`（推理模型；`call_llm` 对含 "5.2" 的 model 自动发 `thinking:{"type":"disabled"}`，否则烧 reasoning_tokens 致 max_tokens 截断返空）。429 用 30/60/90s 长退避（GLM 按分钟限流）。
- **两层补全**：① rule-first（别名 + 金额正则 + Phase B LLM 确认，精确便宜）；② 残余进 `_llm_propose_fallback`（`full_context=True` 让 NCA/权益尾部可见）。
- **三层防脏 override 守卫**：① `failure_candidate_fields` 所有分支排除 `subtotal`（subtotal 是校验目标不是待补明细）；② collect_failures 前先跑 income subtotal adaptation；③ `add_override` 拒绝非 0 `old_value`（只补漏录/为 0 字段）。
- **应用范围**：只应用 `status=approved` 且 `source∈{glm（当前）, kimi（历史兼容）}` 到**年度 clean 宽表**；每条写 `clean_adjustments`，warning 写 `clean_warnings`。**raw_tushare 永不修改**。
- **override clean_category 重分类**：部分 TuShare 字段 bucket 归属对个别公司不成立（典型 `estimated_liab` 预计负债，TuShare 默认非流动但比亚迪列报为流动）。不改 clean.py 静态分类，由 reconciler 在 override 写 `clean_category`，clean.py 应用时只对该公司该期重分类（写 `wide.attrs["bs_reclass"]`，`bs_bucket_sum` 按 reclass 取 bucket）。
- **两轮都不过 → `_offer_annual_plug`**：交互问用户是否塞年度 QA plug。同意 → 写 `Agent/recon/annual_plugs.json`（`period` 为纯年份）→ 重跑 `clean.py --mode annual --allow-annual-plug`。年度 plug 是诚实逃生通道不是常规兜底——关键科目建议拒绝 plug、如实留 exit 3。

### 阶段⑤ 年度核心指标速览 `stage_core_metrics_overview`

clean 年度表通过后覆盖生成 `Agent/core_metrics_overview.{md,json,csv}`。

- 只读 `clean_annual`，不读 forecast/yaml/defaults，不调 LLM，不写生成时间。
- 同一份 `clean_annual` 重跑应保持字节稳定。
- `--mode quarterly` 不更新此文件。

### 阶段⑥ 财务费用细则 + defaults.yaml

- `stage_financial_expense` → `Agent/financial_expense.yaml`：年报财务费用附注按年归档（失败仅 warning 不阻塞）。
- `stage_defaults` → `Agent/defaults.yaml`（唯一 YAML2）：从 `clean_annual` + `meta` + `financial_expense.yaml` 派生，机器平推底座。带 `review_flags` 机器审计标识（如 `latest_outlier: balance_sheet.dividend_payout`、`one_off_candidate: income.cost_abs.*`、`financial_expense_evidence_failed: income.financial_expense`），不阻塞 init，由 `/ka` 消化。clean 未通过则跳过 ⑤⑥。

每阶段结束打印 `⏱ 阶段N 用时 Xm Ys`，最后打印总用时分解（取数/下载/clean/速览/财务费用/defaults）。

---

## 三、Agent 按退出码行动

| 退出码 | 含义 | Agent 要做的 |
|---|---|---|
| **0** | 全链路成功 | 转述 init.py 打印的「数据拉取报告」：哪些纯 TuShare 通过、哪些科目经年报补全、`core_metrics_overview.*` 是否刷新、`defaults.yaml` 的 `review_flags` 是否为 0；若非 0，说明这些 flag 后续由 `/ka` 消化，不是 clean blocker。 |
| **2** | 输入无法解析为唯一 ticker（中文名歧义/无匹配） | 看 stderr 候选；websearch 查"<公司名> A股 股票代码" → 用完整 ticker 重跑。 |
| **3** | 应用年报补数后仍有年度硬校验失败（**真数据问题**） | **先如实告知**：哪一期/哪条 check 失败、reconciler 为何没闭合。**然后**（agent 在线且用户想推进）走 subagent 升级通道。无 agent 在线或 subagent 也找不到证据，才如实留 exit 3。**绝不静默改判成功**。 |
| **1** | 其它异常（API/网络/鉴权/缺 .env） | 报错并给可能原因（TUSHARE_TOKEN、网络、中转站、年报缺失）。 |

### 退出码 2 的 websearch 兜底流程

1. 读 stderr 候选列表（若有）。2. websearch `<用户给的名字> A股 股票代码`。3. 得到 6 位代码 + 交易所 → 拼完整 ticker（沪 `.SH` / 深 `.SZ` / 北 `.BJ`）。4. `python -m src.init <完整ticker>` 重跑。5. 仍失败则把候选连同判断给用户确认，不要乱猜。

---

## 四、exit 3 subagent 升级通道（仅 agent 在线时）

reconciler 是**无人值守地板**：rule + GLM fallback 两轮，关简单/精确案例。但它对某些案例结构性赢不了（典型：BYD 002594 2019/2021 BS 3.2——LLM 把租赁负债映射成不存在的 `lease_ncl`、被守卫挡；或 compound 残差单字段打分闭合不了）。这时由 Agent 派 **subagent 并发啃残差**，能力远强于 reconciler 的单次 GLM 调用：subagent 直接读**干净年报 Markdown**、拿**净残差**（已扣已批准 override）、用 candidate 集**确定性映射字段**。

### 什么时候走升级通道

- init exit 3，**且 agent 在对话里在线**，**且用户想继续推进**（不是要立刻停）。
- 无 agent 在线（工作台重算按钮 / cron / 批量 `py -m src.init`）→ 没有这条通道，直接留 exit 3，靠 reconciler 地板。
- 2010 之前的年度硬失败**不走**这条通道（2010 闸门，reconciler 已降级入库）。

### 通道 A：BS/IS/CF 残差 override 通道（找缺数补 override）

1. **算净残差失败 + subagent 上下文**（确定性）：
   ```bash
   python -m src.recon_subagent_bridge context --ticker <t>
   ```
   内部重跑 `clean --mode annual --no-auto-reconcile`（生产路径应用所有 approved override，含 reclass），解析 `HARD CHECK FAIL` 行得到**净残差失败**，为每个失败算上下文写到 `Agent/recon/subagent_context.json`：`failure`（code/period/净残差/target/calc/direction）、`bucket`、`candidate_fields`、`approved_overrides_for_period`、`reclass_for_period`、`markdown_path`、`section_start`/`section_end`、`net_residual`、`net_direction`。

2. **并发派 subagent**（核心）：一条消息并发派 N 个（一个残差一个，cap ≈6，`general-purpose` 或 `Explore`）。subagent **只读年报 + 返回结构化提案**，不写文件、不跑 clean、不批准自己。返回 JSON 数组合并到 `Agent/recon/subagent_proposals.json`：
   `[{"period","code","field","operation","value_million_cny","annual_report_item","annual_report_value_raw","unit","evidence_lines","reasoning","clean_category?"}, ...]`
   - **多字段联合闭合**：很多残差是 2-3 个字段共同漏报（如紫金 BS 2.2 2025 = oth_eq_invest + oth_illiq_fin_assets + use_right_assets 三项和）。subagent 返回一个 JSON 数组，每字段一个 proposal（共享 period+code）。bridge 按 (period, code) 归组、对集合净影响验闭合。前提：每字段都有独立年报证据行号，不许把残差硬拆给没证据的字段。
   - 找不到证据的失败返回 `{"found": false, "reason": "..."}`，**不凑数**。

3. **服务端验闭合 + 写 approved override**（确定性）：
   ```bash
   python -m src.recon_subagent_bridge apply --ticker <t>
   ```
   读 `subagent_context.json` + `subagent_proposals.json`，对每个失败按提案集合净影响验闭合（防脏配平闸门在代码，不信 subagent 自报 diff）：
   - 提议字段必须在 failure 的 candidate 集内（反幻觉）；
   - `add_override`（补 0/缺字段）：字段有效 bucket == 本 bucket → calc +value；
   - `reclass`（字段移出/移入本 bucket）：calc ∓字段现值；
   - 闭合条件 `|净影响 − 所需影响| < TOLERANCE` 才**整组批准**，否则一组都不批。
   - 验通过写成 override 记录（`source=claude`、`approved_by=claude:high_confidence`、带 `evidence_lines`+`reason`），合并进 `annual_report_overrides.json`（同 (period, field) 已有 approved 则跳过，不覆盖已有 LLM 证据）。

4. **重跑 clean 验证**（闭环必做）：
   ```bash
   python -m src.clean --ticker <t> --mode annual
   ```
   确认之前 `HARD CHECK FAIL` 的 check 现在过。过了再 `--mode all` 把季度表也刷新。bridge apply 只是写 override，真正配平要在 clean 重跑里验证。

5. **如实汇报**：哪些残差被 subagent 用年报证据闭合了（字段 × 期 × 年报行号 × 金额）；哪些 subagent 也找不到证据（诚实留 exit 3，建议人工看年报/口径）；`raw_tushare` 未动，审计在 `clean_adjustments`（source=claude）。

### 通道 B：跨表 7.4 重述豁免通道（不补数，确认重述 → 证据化豁免 → 降级软 warning）

exit 3 的失败里若混有 `跨表 7.4`（上期 CF 期末 ≠ 本期 CF 期初），**走这条完全不同的通道**——不是"找缺数补 override"，而是"确认重述 → 证据化豁免 → clean 降级软 warning"。

**为什么 7.4 不能用 override 闭合**：7.4 残差来自年报重述——公司在新一年年报比较列里追溯重述上年期末现金，TuShare 存的却是各年原始披露值，边界不衔接。override 一侧会破坏该侧 CF 5.5（期末=期初+净增加），改净增加又级联到 CF 5.4/5.1-5.3；多年连续重述要彻底闭合得整体重载被重述年份的整张现金流量表，fragile 且破坏 TuShare 口径。**重述是公司披露的会计事件、非数据错误**，故走豁免降级（与 2010 闸门同性质：有据、可审计，非静默改判）。潍柴动力 000338 实测：2021/2022 两条 7.4 经此通道豁免后年度 10 期全过。

**5 步流程**：

1. **算失败 + 上下文**（确定性）：`python -m src.recon_subagent_bridge context --ticker <t>`，bridge 为每个 7.4 失败算 `build_restatement_context`：从 message 解析 `prev_end_cash`/`cur_beg_cash`/残差/方向，定位本期年报合并现金流量表期初/期末现金行号（`cf_section_hint`），写到 `subagent_context.json`（`kind:"restatement"`）。

2. **并发派 subagent 确认重述**（一个 7.4 失败一个）：subagent 读本期年报合并现金流量表期末段（两列：本期 | 上年比较列），抽两个数——**本期期初现金**（本期列）与**上年比较列期末现金**（上年列，重述后）+ 证据行号，返回：
   ```json
   [{"confirmed": true, "period": "<本期>", "cur_beg_disclosed_yuan": <元>,
     "prev_end_comparative_yuan": <元>, "evidence_lines": "<行号-行号; 行号-行号>",
     "reasoning": "<为何是披露重述>"}]
   ```
   合并到 `Agent/recon/subagent_restatement_proposals.json`。读不到/对不上 → `{"confirmed": false, ...}`，**不凑数**。

3. **服务端验证据 + 写豁免**（确定性，6 道闸门全在代码）：
   ```bash
   python -m src.recon_subagent_bridge apply-restatements --ticker <t>
   ```
   `evaluate_restatement_proposal` 闸门：① `confirmed==true`；② subagent 引用行号里**真实出现**其声称的两个元金额（反幻觉，bridge 自己读 markdown 行号校验）；③ 本期期初(披露)==上年比较列期末(披露)（年报内部自洽）；④ 本期期初(披露)==TuShare 本期期初（TuShare 本期值是对的）；⑤ 本期期初(披露)≠TuShare 上年期末（确属重述，非数据错误）；⑥ 残差吻合。全过才写 `restatement_exemptions.json`（`source=claude`，带 evidence_lines+reason）。

4. **重跑 clean 验证**（闭环必做）：`python -m src.clean --ticker <t> --mode annual`。clean.py 加载 `restatement_exemptions.json`，对豁免边界把 7.4 从硬错误降级为 `clean_warnings`（带"重述豁免…source=claude…非数据错误"），残差需与豁免记录吻合（防脏豁免：TuShare 值变动后旧豁免自动失效）。过了再 `--mode all`。

5. **如实汇报**：哪些边界被豁免（期 × 上期 × 残差 × 年报行号）、哪些 subagent 没确认（诚实留 exit 3）。`raw_tushare` 未动；豁免审计在 `clean_warnings`（source=claude）。

**纪律**：subagent 只读只确认；验证据/写豁免/降级全在 bridge+clean 代码。`--no-restatement-exemptions` 可关闭。豁免只降级 7.4 这一类经年报确认的重述边界，**绝不**用来掩盖 BS/IS/CF 内部配平失败——那些仍走 override 通道或诚实留 exit 3。

### subagent prompt 模板要点

> 你是 A 股财报核对员。给一个硬校验残差失败：`<failure 全字段>`。扣除已批准 override 后的**净残差**是 `<net_residual>` 百万元，calc 偏`<低/高>`。candidate TuShare 字段（只能用列表里的字段）：`<candidate_fields>`。本期已批准 override：`<approved_overrides_for_period>`。年报 Markdown：`<markdown_path>`，报表段在行 `<section_start>-<section_end>`。
>
> 任务：用 Read 工具读该年报 section 全文，找出年报里哪些明细科目金额能解释净残差。映射到 candidate 字段（**只能用列表里的字段名**，不许编 lease_ncl 这类不存在的）。判断操作：`add_override`（字段为 0/缺，补值）还是 `reclass`（字段有值但 bucket 归错，带 clean_category）。
>
> **单字段能闭合就返回单字段；单字段闭合不了但 2-3 个字段之和能精确闭合，就返回多个 proposal（每字段一条，共享 period+code，各自带独立证据行号）**。
>
> 返回**严格 JSON 数组**（单字段也包成单元素数组）：
> ```json
> [{"found": true, "period": "...", "code": "...", "field": "<candidate字段名>",
>   "operation": "add_override|reclass", "value_million_cny": <百万元>,
>   "annual_report_item": "<科目名>", "annual_report_value_raw": <元>,
>   "unit": "元人民币|千元人民币", "evidence_lines": "<行号-行号: 证据>",
>   "reasoning": "<为什么闭合净残差>", "clean_category": "<仅reclass填>"}]
> ```
> 找不到任何能精确闭合的字段（单字段或多字段组合都不吻合），返回 `[{"found": false, "reason": "..."}]`。
>
> 纪律：① 只能用 candidate 列表里的字段；② 每字段金额必须来自年报原文、带行号；③ 多字段组合必须各项都有独立证据、和精确闭合残差（容差 1 百万元），**不许把残差硬拆给没有证据的字段凑数**；④ 找不到就 found:false，不许硬塞。

### 为什么 subagent 赢 reconciler 的 GLM

| 维度 | reconciler GLM | subagent |
|---|---|---|
| 年报文本 | PyMuPDF 抽散的 snippet（jumbled） | 直接 Read 干净 Markdown 全文 |
| 残差 | compound（重分类未反映）单字段打分闭合不了 | 净残差（已扣 override）单字段即可闭合 |
| 字段映射 | GLM 发字段名会飘（lease_ncl/null） | candidate 集确定性映射（bridge `resolve_candidate_field`） |
| 通用性 | 守卫没见过的公司形态卡死 | 能推理应付新形态 |

### 升级通道纪律（必须遵守）

- **subagent 只读只提案**：写/批准/验闭合全在 bridge 代码 + Agent（编排者）。防脏配平闸门在 `evaluate_proposals`，不信 subagent 自报。
- **raw_tushare 永不被修改**；override 只进年度 clean 宽表 + `clean_adjustments` 审计，source=claude 与 glm/kimi 同等可追溯。
- **不闭环不算成功**：bridge apply 写完 override 必须重跑 clean 验证通过才算；clean 没过就如实报。
- **诚实于找不到**：subagent 找不到证据的失败，留 exit 3，不塞 plug、不脏配平（关键科目尤其如此）。

---

## 五、关键纪律（贯穿）

1. **退出码 3 绝不改判成功**——这是 clean-data blocker，代表当前年度 clean 数据不可信。
2. **raw_tushare 永不被修改**。年报补数只进 clean 年度宽表，并写入 `clean_adjustments`/`clean_warnings` 审计。
3. 失败的那次 clean 运行不会被改判；override 只在重跑时应用——这套两段式已由 `init.py` 自动完成，无需手工敲 `annual_report_reconciler.py`。
4. **2010 闸门**：年报核对（reconciler）只对 2010 年及以后的年度硬校验失败触发。2010 之前的年度硬校验失败被 clean.py 降级为 warning 直接入库。汇报时说清"2010 前为直接入库、未经年报核对"。
5. **pre-IPO 闸门**：上市前年份（早于本地最早年报 Markdown 年份）的年度硬校验失败同样降级 warning 直接入库。汇报时说清"pre-IPO 年为直接入库、未经年报核对"。
6. 汇报用事实，不用营销词。补全过的科目要讲清来源是年报、可追溯。

---

## 六、性能特性

- **"init 慢"≈"在等串行 LLM"，几乎从不是 TuShare 取数或年报下载慢。** 取数 0.8s/次、下载多线程；真正的墙钟花在两处 LLM 循环：clean 年度失败后的 **reconcile 配平确认**，和 **财务费用细则**逐年分析。排查慢按全局 CLAUDE.md 的调试顺序：先查并发/超时，最后才怀疑模型。
- **阶段并行（2026-06-25）**：`init.py` 的阶段不再全串行——② 年报/季报下载丢后台线程，与 ③ 首轮 clean 并行。首轮 clean 只读 `raw_tushare`（不读年报），纯 TuShare 配平的公司秒级通过 ③，不等 ② 下载完即进 ④。仅当首轮 clean 年度硬失败（reconciler 需要年报 Markdown）时才 `join` ② 再触发 reconciler。干净公司把整段下载移出关键路径。
- **clean 同进程（2026-06-25）**：`init.py` 改同进程调 `clean_all()`（不再 `python -m src.clean` subprocess 套娃），两轮 backfill 的 4-6 次 clean 重跑省掉每次 Python 冷启动 + pandas/tushare 重复 import。reconciler 仍由 init 显式调 `auto_reconcile_annual_failure` 触发（其内部仍 subprocess reconciler，stderr 流式回显保留）。CLI `python -m src.clean` 入口不变。
- **这两处 LLM 循环已并发**（有界线程池，`LLM_MAX_WORKERS` 默认 6）：N 个失败年×bucket / N 个年份不再相加，墙钟≈最慢的一次。每次调用仍各自保留超时+重试+`chunk_errors` 分片审计。
- **首跑 vs 复跑成本不对称**：首跑要付 K 次 LLM 确认 + K 次 PDF→Markdown 解析；复跑几乎免费（年报 PDF/MD、`financial_expense.yaml`、approved override 全部缓存/跳过）。`--force` 会重新付全部 LLM 成本，仅在确需重算时用。
- 单公司还嫌慢可临时调大并发：`LLM_MAX_WORKERS=8 python -m src.init <公司>`（受 GLM/Kimi 速率限制约束，别盲目调高；默认 5 是为避开 GLM 按分钟限流，调高易触发 429）。
- **轮询 reconciler 至少 sleep 300s**：年度失败触发强触发 reconciler 后，LLM 配平确认循环通常要 5-15 分钟。中途轮询输出文件时，**两次 `tail` 之间 `sleep` 至少 300 秒**——reconciler 的 GLM 调用是批量静默期（stdout 无逐行回显），sleep 太短会反复读到同一截日志，误判"卡死"。复杂公司（失败年份≥8、需要两轮 fallback）宁可一次 sleep 600s 也别频繁轮询。后台跑完会主动通知。
- **复杂公司务必后台跑**（`run_in_background: true`），别前台 `| tail`：复杂公司首跑要几分钟到十几分钟，前台跑撞 10 分钟超时，且 `| tail -N` 会全量缓冲到跑完才回显，用户盯黑屏。init 现在逐行流式回显 clean/reconciler 日志（`PYTHONUNBUFFERED=1`），后台输出文件里能实时看到进度。

---

## 七、完整产物清单（`companies/{公司}/` 下）

| 路径 | 内容 | 阶段 |
|---|---|---|
| `Agent/data.db` | `raw_tushare` / `meta` / `clean_annual` / `clean_quarterly` / `clean_adjustments` / `clean_warnings` | ①③ |
| `公告/年报/{年份}_年度报告.{pdf,md}` | 年报 PDF + Markdown（修订版 `_修订版`） | ② |
| `Agent/OfficialBreakdowns/business_revenue_breakdown{_h1,_all}.{csv,jsonl}` | 官方拆分（四维营收+成本+毛利率、产销量、成本构成；年度 / 近 3 年半年报 / 合并） | ② |
| `Agent/core_metrics_overview.{md,json,csv}` | 年度核心指标速览（只读 clean_annual，字节稳定） | ⑤ |
| `Agent/financial_expense.yaml` | 财务费用附注多年档案 | ⑥ |
| `Agent/defaults.yaml` | 机器平推底座（唯一 YAML2，带 `review_flags`） | ⑥ |
| `Agent/recon/` | reconciler/subagent 的 evidence JSON、override、proposals、restatement_exemptions、annual_plugs | ④ |
| `Agent/.modelking/` | 内部编译产物（非人工维护界面） | — |

---

## 八、重要边界

- **init 产出的 `OfficialBreakdowns` 是年报原文披露的官方营收拆分明细（事实抽取）**，给 `/ka`、`/brkd` 当素材。
- **建模意义上的业务拆分**（分业务线收入×毛利率×驱动因子假设、写进 `核心假设.md`）**不是 init 的职责**——那是 `/brkd`（业务预理解）+ `/ka`（核心假设）的活，init 只备齐财务数据和官方素材。
- init 不做预测、不做 DCF、不改 yaml1；DCF 走 `py -m src.forecast`。
- init 不适用于金融企业（comp_type≠1 会被过滤）；季度 BS 明细不完整、CF 5.5 残差只允许显式 QA plug + warning，不做静默补数。

---

## 九、验收方式

```bash
# 1. 语法检查
py -m py_compile src/init.py src/clean.py src/data_fetcher.py src/report_downloader.py

# 2. 一键拉取并校验
py -m src.init 300866.SZ

# 单独跑 clean（CLI 入口不变，workbench 等仍可用）
py -m src.clean --ticker 300866.SZ --verbose
#   --mode annual|quarterly|all · --no-overrides · --no-auto-reconcile · --allow-annual-plug · --db <path>

# 检查：字段覆盖 income=86×期数, balancesheet=150×期数, cashflow=89×期数
# 抽查单位：revenue/total_mv=百万元, total_share=百万股, roe=小数
```
