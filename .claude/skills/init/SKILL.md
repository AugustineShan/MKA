---
name: init
description: 一键拉取并校验某 A 股公司的财务数据。当用户说 "init 美的集团"、"init 000333"、"init 600519.SH"、"初始化某公司数据"、"拉一下某公司财报" 时使用。自动编排 TuShare 取数 → 年报下载 → 配平校验 → 年报补全重跑 → 年度核心指标速览，并输出数据拉取报告。
---

# init — 一键拉取并校验 A 股财务数据

把一个公司（名称 / 裸代码 / 完整 ticker）跑完 MKA 全流程：
取数 → 年报下载 → 清洗配平校验 →（必要时）年报确认补全后重跑 → 生成年度核心指标速览。
确定性编排由 `init.py` 完成；你（Agent）只负责输入解析兜底、读退出码、如实汇报。

汇报风格：像数据到位情况会，不像终端日志转发。成功时先说数据更新到哪一年、哪些校验通过、哪些科目用年报补全、哪些下游文件可用；失败时先说卡在哪个检查、影响什么、下一步怎么处理。不要把长日志原样贴给用户。

## 触发

用户出现下列意图之一即用本 skill：
- "init <公司>"、"初始化 <公司>"、"拉一下 <公司> 的财报/数据"
- 给出公司名、裸代码或完整 ticker，要求建立/更新其财务数据

## 怎么做

### 第 1 步：直接调用 init.py

```bash
python -m src.init <用户输入>
```

`<用户输入>` 原样传入即可——脚本能处理这三种形态：
- 完整 ticker：`000333.SZ`
- 裸代码：`000333`（自动补后缀）
- 中文公司名：`美的集团`（用 TuShare stock_basic 解析）

批量：`python -m src.init 000333.SZ 600519.SH 美的集团`

**复杂公司务必后台跑，别前台 `| tail`**：复杂公司（金融子公司、多年 BS 缺明细、年度失败多）首跑要几分钟到十几分钟——前台跑会撞 10 分钟超时，且 `| tail -N` 会把输出全量缓冲到跑完才回显，用户盯着黑屏。所以：
- **后台执行**（`run_in_background: true`），不接 `| tail`。init 现在逐行流式回显 clean/reconciler 日志（`PYTHONUNBUFFERED=1`），后台输出文件里能实时看到「Analyzing BS 2.2 2018...」「第 1 轮...」。
- 每阶段结束打印 `⏱ 阶段N 用时 Xm Ys`，最后打印总用时分解（取数/下载/clean/速览/财务费用）。即使用户只看最终报告，也能知道「年报下载了多久、核对了多久」。
- 后台跑完会通知；中途可 Read 输出文件看进度。


- `--force`：全量重拉（清空旧 raw_tushare 重拉）。仅当用户明确要求"强制刷新/重新拉"时用。
- `--mode annual|quarterly|all`：默认 `all`。
- `--no-markdown` / `--force-markdown`：年报 Markdown 控制。

**幂等**：脚本默认增量——当日已拉取则跳过取数，已存在的年报 PDF/MD 跳过下载，
年报补数只在重跑时应用。所以反复 `init` 同一公司是安全且廉价的，用于日常更新数据。

clean 年度表成功后，`init.py` 会覆盖生成给后续 Agent/LLM 读的年度事实速览：

```text
companies/{公司}/Agent/core_metrics_overview.md
companies/{公司}/Agent/core_metrics_overview.json
companies/{公司}/Agent/core_metrics_overview.csv
```

它只读 `clean_annual`，不读 forecast/yaml/defaults，不调用 LLM，不写生成时间；同一份 `clean_annual` 重跑应保持字节稳定。`--mode quarterly` 不更新这份年度速览。

### 第 2 步：按退出码决定下一步

| 退出码 | 含义 | 你要做的 |
|--------|------|----------|
| **0** | 全链路成功 | 把 init.py 打印的「数据拉取报告」转述给用户。重点说明：哪些是纯 TuShare 通过、哪些科目经年报确认后补全（如美的的 `lending_funds`），以及 `core_metrics_overview.*` 是否已刷新。 |
| **2** | 输入无法解析为唯一 ticker（中文名歧义/无匹配） | 看 stderr 列出的候选；**用 websearch 查"<公司名> A股 股票代码"** 确认正确代码，然后用完整 ticker 重新 `python init.py 000333.SZ`。 |
| **3** | 应用年报补数后仍有年度硬校验失败（**真数据问题**） | **先如实告知用户**：哪一期/哪条 check 失败、reconciler 为何没能闭合。**然后**（agent 在线时）走下面的「退出码 3 subagent 升级通道」——派并发 subagent 啃残差。若用户明确不要升级或 subagent 也找不到证据，才如实留 exit 3。**绝不静默改判成功**。 |
| **1** | 其它异常（API/网络/鉴权/缺 .env） | 报错并给出可能原因（TUSHARE_TOKEN、网络、中转站、年报缺失）。 |

### 退出码 2 的 websearch 兜底流程

1. 读 stderr 候选列表（若有）。
2. websearch：`<用户给的名字> A股 股票代码`。
3. 得到 6 位代码 + 交易所 → 拼成完整 ticker（沪 `.SH` / 深 `.SZ` / 北 `.BJ`）。
4. `python init.py <完整ticker>` 重跑。
5. 仍失败则把候选连同你的判断给用户确认，不要乱猜。

## 退出码 3 的 subagent 升级通道（agent 在线时）

reconciler 是**无人值守地板**：rule + GLM fallback 两轮，关简单/精确案例。但它对某些案例结构性赢不了（典型：BYD 002594 2019/2021 BS 3.2——LLM 把租赁负债映射成不存在的 `lease_ncl`、被守卫挡；或 compound 残差单字段打分闭合不了）。这时由你（agent）派 **subagent 并发啃残差**，能力远强于 reconciler 的单次 GLM 调用：subagent 直接读**干净年报 Markdown**、拿**净残差**（已扣已批准 override）、用 candidate 集**确定性映射字段**。

### 什么时候走升级通道

- init exit 3，**且你在对话里（agent 在线）**，**且用户想继续推进**（不是要立刻停）。
- 无 agent 在线（工作台重算按钮 / cron / 批量 `py -m src.init`）→ 没有这条通道，直接留 exit 3，靠 reconciler 地板。
- 2010 之前的年度硬失败**不走**这条通道（2010 闸门，reconciler 已降级入库）。

### 完整 7 步流程

#### 第 1 步：算净残差失败 + subagent 上下文（确定性，bridge `context`）

```bash
python -m src.recon_subagent_bridge context --ticker 002594.SZ
```

它内部重跑 `clean --mode annual --no-auto-reconcile`（用 clean.py 自己的生产路径应用所有 approved override，含 reclass），解析 `HARD CHECK FAIL` 行得到**净残差失败**（reconciler 内部 collect_failures 曾出现重分类未反映进残差的问题，这里绕开）。再为每个失败算 subagent 所需上下文，写到 `companies/{公司}/Agent/recon/subagent_context.json`：

每个 context 含：`failure`（code/period/净残差/target/calc/direction）、`bucket`、`candidate_fields`（field/description/alias/value/clean_category）、`approved_overrides_for_period`、`reclass_for_period`、`markdown_path`、`section_start`/`section_end`（报表段行号范围）、`net_residual`、`net_direction`。

读它的输出 summary，确认有几个残差失败、各有年报 Markdown 没有。

#### 第 2 步：并发派 subagent（核心）

**一条消息里并发派出 N 个 Agent subagent**（一个残差失败一个，cap ≈6 并发；用 `general-purpose` 或 `Explore` 类型，subagent_type 视情况）。每个 subagent 的任务见下面 prompt 模板。subagent **只读年报 + 返回结构化提案**，不写文件、不跑 clean、不批准自己。

把每个 subagent 返回的提案收集成一个 JSON 列表，写到：

```
companies/{公司}/Agent/recon/subagent_proposals.json
```

格式：`[{"period","code","field","operation","value_million_cny","annual_report_item","annual_report_value_raw","unit","evidence_lines","reasoning","clean_category?"}, ...]`

**多字段联合闭合**（重要）：很多残差不是单字段漏报，而是 2-3 个字段共同漏报（如紫金 BS 2.2 2025 = oth_eq_invest + oth_illiq_fin_assets + use_right_assets 三项和）。subagent 应返回**一个 JSON 数组**，每个字段一个 proposal 对象（共享同一 period+code）。bridge `evaluate_proposals` 按 (period, code) 归组、对集合净影响验闭合——所以多字段集合能闭合就整组批准。**前提**：每个字段都必须有独立的年报证据行号，不许把残差硬拆给没有证据的字段。

找不到证据的失败，subagent 返回 `{"found": false, "reason": "..."}`，**不要凑数**——该条不进 proposals。

#### 第 3 步：服务端验闭合 + 写 approved override（确定性，bridge `apply`）

```bash
python -m src.recon_subagent_bridge apply --ticker 002594.SZ
```

它读 `subagent_context.json` + `subagent_proposals.json`，对每个失败**按提案集合的净影响验闭合**（防脏配平闸门在代码，不信 subagent 自报 diff）：

- 提议字段必须在 failure 的 candidate 集内（反幻觉）；
- `add_override`（补 0/缺字段）：字段有效 bucket == 本 bucket → calc +value；
- `reclass`（字段移出/移入本 bucket）：calc ∓字段现值；
- 闭合条件 `|净影响 − 所需影响| < TOLERANCE` 才**整组批准**，否则一组都不批。

验通过的提案写成 override 记录（`source=claude`、`approved_by=claude:high_confidence`、带 `evidence_lines`+`reason`），合并进 `annual_report_overrides.json`（同 (period, field) 已有 approved 则跳过，不覆盖已有 LLM 证据）。输出 verdict：哪些 closed、哪些 not_closed。

#### 第 4 步：重跑 clean 验证

```bash
python -m src.clean --ticker 002594.SZ --mode annual
```

确认之前 `HARD CHECK FAIL` 的 check 现在过。过了再 `--mode all` 把季度表也刷新。**这一步是闭环必做**——bridge apply 只是写 override，真正配平要在 clean 重跑里验证。

#### 第 5 步：如实汇报

告诉用户：
- 哪些残差被 subagent 用年报证据闭合了（字段 × 期 × 年报行号 × 金额）；
- 哪些 subagent 也找不到证据（诚实留 exit 3，建议人工看年报/口径）；
- `raw_tushare` 未动，审计在 `clean_adjustments`（source=claude）。

### subagent prompt 模板（要点，按此派发）

> 你是 A 股财报核对员。给一个硬校验残差失败：`<failure 全字段>`。
> 扣除已批准 override 后的**净残差**是 `<net_residual>` 百万元，calc 偏`<低/高>`（direction=`<net_direction>`）。
> candidate TuShare 字段（只能用列表里的字段）：`<candidate_fields>`。
> 本期已批准 override（有些字段已补/已重分类，别重复提）：`<approved_overrides_for_period>`。
> 年报 Markdown：`<markdown_path>`，报表段在行 `<section_start>-<section_end>`。
>
> 任务：用 Read 工具读该年报 section 的干净全文，找出年报里哪些明细科目的金额能解释这个净残差。把它映射到 candidate 字段（**只能用列表里的字段名**，不许编 lease_ncl 这类不存在的）。判断操作：`add_override`（字段为 0/缺，补值）还是 `reclass`（字段有值但 bucket 归错，需带 clean_category）。
>
> **单字段能闭合就返回单字段；单字段闭合不了但 2-3 个字段之和能精确闭合，就返回多个 proposal（每个字段一条，共享 period+code，各自带独立证据行号）**。bridge 按集合验闭合。
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
> 纪律：① 只能用 candidate 列表里的字段；② 每个字段金额必须来自年报原文、带行号；③ 多字段组合必须各项都有独立证据、和精确闭合残差（容差 1 百万元），**不许把残差硬拆给没有证据的字段凑数**；④ 找不到就 found:false，不许硬塞。

### 跨表 7.4 重述豁免通道（与 BS 残差通道并行，**不补数**）

exit 3 的失败里若混有 `跨表 7.4`（上期CF期末 ≠ 本期CF期初），**走这条完全不同的通道**——不是 BS 残差的"找缺数补 override"，而是"确认重述 → 证据化豁免 → clean 降级软 warning"。

**为什么 7.4 不能用 override 闭合（踩过坑，别再试）**：7.4 残差来自年报重述——公司在新一年年报比较列里追溯重述上年期末现金，TuShare 存的却是各年原始披露值，边界不衔接。override 一侧会破坏该侧 CF 5.5（期末=期初+净增加），改净增加又级联到 CF 5.4/5.1-5.3；多年连续重述（每年报都在再追溯）要彻底闭合得整体重载被重述年份的整张现金流量表，fragile 且破坏 TuShare 口径。**重述是公司披露的会计事件、非数据错误**，故走豁免降级（与 2010 闸门同性质：有据、可审计，非静默改判）。潍柴动力 000338 实测：2021/2022 两条 7.4 经此通道豁免后年度 10 期全过。

**5 步流程**：

1. **算失败 + 上下文**（确定性）：
   ```bash
   python -m src.recon_subagent_bridge context --ticker <t>
   ```
   bridge 重跑 clean 取净残差失败，为每个 `跨表 7.4` 失败算 `build_restatement_context`：从 message 解析 `prev_end_cash`/`cur_beg_cash`/残差/方向，定位本期年报合并现金流量表期初/期末现金行号（`cf_section_hint`），写到 `subagent_context.json`（`kind:"restatement"`）。

2. **并发派 subagent 确认重述**（一个 7.4 失败一个）：subagent 读本期年报合并现金流量表期末段（两列：本期 | 上年比较列），抽两个数——**本期期初现金**（本期列）与**上年比较列期末现金**（上年列，重述后）+ 证据行号，返回：
   ```json
   [{"confirmed": true, "period": "<本期>", "cur_beg_disclosed_yuan": <元>,
     "prev_end_comparative_yuan": <元>, "evidence_lines": "<行号-行号; 行号-行号>",
     "reasoning": "<为何是披露重述>"}]
   ```
   把各 subagent 输出合并到 `companies/{公司}/Agent/recon/subagent_restatement_proposals.json`。读不到/对不上 → `{"confirmed": false, ...}`，**不凑数**。

3. **服务端验证据 + 写豁免**（确定性，6 道闸门全在代码）：
   ```bash
   python -m src.recon_subagent_bridge apply-restatements --ticker <t>
   ```
   `evaluate_restatement_proposal` 闸门：① `confirmed==true`；② subagent 引用的行号里**真实出现**其声称的两个元金额（反幻觉，bridge 自己读 markdown 行号校验，不信自报）；③ 本期期初(披露)==上年比较列期末(披露)（年报内部自洽）；④ 本期期初(披露)==TuShare 本期期初（TuShare 本期值是对的）；⑤ 本期期初(披露)≠TuShare 上年期末（确属重述，非数据错误）；⑥ 残差吻合。全过才写 `restatement_exemptions.json`（`source=claude`，带 evidence_lines+reason），同 period 已有则跳过。

4. **重跑 clean 验证**（闭环必做）：
   ```bash
   python -m src.clean --ticker <t> --mode annual
   ```
   clean.py 加载 `restatement_exemptions.json`，对豁免边界把 7.4 从硬错误降级为 `clean_warnings`（带"重述豁免…source=claude…非数据错误"），残差需与豁免记录吻合（防脏豁免：TuShare 值变动后旧豁免自动失效）。过了再 `--mode all`。

5. **如实汇报**：哪些边界被豁免（期 × 上期 × 残差 × 年报行号）、哪些 subagent 没确认（诚实留 exit 3）。`raw_tushare` 未动；豁免审计在 `clean_warnings`（source=claude）。

**纪律**：subagent 只读只确认；验证据/写豁免/降级全在 bridge+clean 代码。`--no-restatement-exemptions` 可关闭。**关键**：豁免只降级 7.4 这一类经年报确认的重述边界，**绝不**用来掩盖 BS/IS/CF 内部配平失败——那些仍走 override 通道或诚实留 exit 3。

### 为什么 subagent 赢 reconciler 的 GLM（理解原理，便于排查）

| 维度 | reconciler GLM | subagent |
|---|---|---|
| 年报文本 | PyMuPDF 抽散的 snippet（jumbled） | 直接 Read 干净 Markdown 全文 |
| 残差 | compound（重分类未反映）单字段打分闭合不了 | 净残差（已扣 override）单字段即可闭合 |
| 字段映射 | GLM 发字段名会飘（lease_ncl/null） | candidate 集确定性映射（bridge `resolve_candidate_field`） |
| 通用性 | 守卫没见过的公司形态卡死 | 能推理应付新形态 |

### 升级通道的纪律（必须遵守）

- **subagent 只读只提案**：写/批准/验闭合全在 bridge 代码 + 你（编排者）。防脏配平闸门在 `evaluate_proposals`，不信 subagent 自报。
- **raw_tushare 永不被修改**；override 只进年度 clean 宽表 + `clean_adjustments` 审计，source=claude 与 glm/kimi 同等可追溯。
- **不闭环不算成功**：bridge apply 写完 override 必须重跑 clean 验证通过才算；clean 没过就如实报。
- **诚实于找不到**：subagent 找不到证据的失败，留 exit 3，不塞 plug、不脏配平（关键科目尤其如此）。

## 纪律（必须遵守）

- **退出码 3 绝不改判成功**。这是 clean-data blocker，代表当前年度 clean 数据不可信。
- **raw_tushare 永不被修改**。年报补数只进 clean 年度宽表，并写入 `clean_adjustments`/`clean_warnings` 审计。
- 失败的那次 clean 运行不会被改判；override 只在重跑时应用——这套两段式已由 `init.py` 自动完成，你无需手工敲 `annual_report_reconciler.py`。
- **2010 闸门**：年报核对（reconciler）只对 **2010 年及以后**的年度硬校验失败触发。2010 之前的年度硬校验失败被 `clean.py` 降级为 warning **直接入库**（写进 `clean_annual`，不阻塞、不核对）。所以老公司（含 2010 前数据）的早期年份不会卡在 reconciler 上，汇报时要说清"2010 前为直接入库、未经年报核对"。闸门常量 `clean.RECONCILE_MIN_YEAR=2010`。
- **pre-IPO 闸门**：上市公司上市前年份（早于本地最早年报 Markdown 的年份，由 `clean.earliest_annual_md_year` 扫描 `公告/年报/*_年度报告.md` 判定）的年度硬校验失败同样**降级为 warning 直接入库**——上市前 TuShare 数据源自招股说明书、cninfo 无该年年报 MD，reconciler 无 MD 可核对，对不上属正常。`init.py` 在年报下载完成后重跑 clean 让闸门生效，pre-IPO 年由此通过、不触发 reconciler。汇报时要说清"pre-IPO 年（如新上市公司 2017-2020）为直接入库、未经年报核对"。无年报 MD 时闸门关闭。
- 汇报用事实，不用营销词。补全过的科目要讲清来源是年报、可追溯。

## 性能与耗时预期（通用，排查"慢"先看这里）

- **"init 慢"≈"在等串行 LLM"，几乎从不是 TuShare 取数或年报下载慢。** 取数 0.8s/次、下载已多线程；真正的墙钟时间花在两处 LLM 循环：clean 年度失败后的 **reconcile 配平确认**，和 **财务费用细则**逐年分析。排查慢按全局 CLAUDE.md 的调试顺序：先查并发/超时，最后才怀疑模型。
- **阶段并行（2026-06-25）**：`init.py` 的 5 阶段不再全串行——② 年报/季报下载丢后台线程，与 ③ 首轮 clean **并行**。首轮 clean 只读 `raw_tushare`（不读年报），纯 TuShare 配平的公司秒级通过 ③，不等 ② 下载完即进 ④。仅当首轮 clean 年度硬失败（reconciler 需要年报 Markdown）时才 `join` ② 再触发 reconciler。④ 核心速览 / ⑤ 财务费用仍按原序在 ② join 后跑（⑤ 读年报 Markdown）。脏公司（需 reconciler）省不下 ②，但干净公司把整段下载移出关键路径。
- **clean 同进程（2026-06-25）**：`init.py` 改同进程调 `clean_all()`（不再 `python -m src.clean` subprocess 套娃），两轮 backfill 的 4-6 次 clean 重跑省掉每次 Python 冷启动 + pandas/tushare 重复 import。reconciler 仍由 init 显式调 `auto_reconcile_annual_failure` 触发（其内部仍 subprocess reconciler，stderr 流式回显保留）。`HARD CHECK FAIL` 行仍由 `validate_wide` 打到 stderr，init 另从 `CheckError.errors` 结构化取全量硬失败供 plug 提示。CLI `python -m src.clean` 入口不变（workbench 等仍可用）。
- **这两处 LLM 循环已并发**（有界线程池，`LLM_MAX_WORKERS` 默认 6）：N 个失败年×bucket / N 个年份不再相加，墙钟≈最慢的一次。每次调用仍各自保留超时+重试+`chunk_errors` 分片审计，不会因并发静默吞错。公司失败年份很多时首跑仍要几分钟，但已是"最慢一次"而非"逐次相加"，属正常。
- **首跑 vs 复跑成本不对称**：首跑要付 K 次 LLM 确认 + K 次 PDF→Markdown 解析；复跑几乎免费（年报 PDF/MD、`financial_expense.yaml`、approved override 全部缓存/跳过）。所以反复 init 同一公司廉价。`--force` 会重新付全部 LLM 成本，仅在确需重算时用。
- 单公司还嫌慢可临时调大并发：`LLM_MAX_WORKERS=8 python -m src.init <公司>`（受 GLM/Kimi 速率限制约束，别盲目调高；默认 5 是为避开 GLM 按分钟限流，调高易触发 429）。
- **轮询 reconciler 至少 sleep 300s**：年度失败触发强触发 reconciler 后，LLM 配平确认循环（rule + GLM fallback 两轮、多年×多 bucket 并发）通常要 5-15 分钟。中途轮询输出文件时，**两次 `tail` 之间 `sleep` 至少 300 秒**——reconciler 的 GLM 调用是批量静默期（stdout 没有逐行回显），sleep 太短会反复读到同一截日志，误判"卡死"。300s 以下 sleep 是浪费 token 还烧缓存（5 分钟缓存 TTL 边界）。复杂公司（失败年份≥8、需要两轮 fallback）宁可一次 sleep 600s 也别频繁轮询。后台跑完会主动通知，不急就直接等通知。

## 报告怎么转述给用户

init.py 已打印结构化报告，包含：
- 三阶段状态（取数 / 年报 / 校验）
- 年度/季度期数
- `clean_adjustments`：年报确认后补全的科目（字段 × 期数 × failure_code）
- `clean_warnings`：季度 QA plug、软校验等

转述时突出两点：**①纯 TuShare 是否全部配平通过；②哪些科目动用了年报确认补全、为什么**。
若 `clean_adjustments` 为空，明确告诉用户"全部为 TuShare 原始数据，未使用任何年报补数"。
