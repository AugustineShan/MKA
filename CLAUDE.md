# MKA - A股财务数据拉取与校验系统

两阶段流水线：① 从 TuShare Pro API 拉取三表数据 → 标准化 → 入库 SQLite；② 从 SQLite 读取原始数据 → 透视宽表 → 严格配平校验 → 写入 SQLite clean 表。

## 🧭 会计问题入口(改字段分类/排序/标签先看这里)

**所有会计科目问题 → 查 `src/field_registry.yaml`。** 这是三表 325 个 TuShare 字段的唯一真源:每个字段归属哪张表/哪个 bucket/第几行(会计序)/中文标签/是否小计/resolve 父子/符号语义,全部声明在此一处。`clean.py` 的校验分类、`workbench.py` 的前端排序与标签、`docs/数据格式参考.md` 都从它派生。改一处,三处同步。**改字段分类/排序/标签只编辑这个 YAML,不要再去找 clean.py 的分类字典或 workbench 的排序声明(它们已不存在,都是从 registry import)。** 详细用法见 `docs/会计系统.md`(改会计科目必读)。

## 🔴 开发总原则：通用性高于一切（所有开发之上的第一原则）

**本系统的开发目的就是兼容各种公司——不限制在任何一家公司、永远为千奇百怪的公司设计，是所有开发决策的第一原则。**

- **不写死任何公司的特征**：行名、业务线数量、公式族、科目、单位、拆分层级，都随公司千变万化。绝不把"牛奶的销量/吨价/4 条线"这类某一家的形状焊进代码、模板、契约或校验器。
- **驱动来自声明，不来自样本**：模板/契约/校验逻辑必须由"这家公司声明了什么结构"驱动（family、anchor、unit、path 都是声明式），而不是由某个样本公司的固定形状驱动。换任何公司，只要它如实声明结构就能跑。
- **看到自己在为某家公司特判，就停**：想 special-case 新乳业（或任何当前样本）时，那是信号——退一步把它一般化。样本只是用来验证"形"，不是用来定义结构。
- **长尾优先于顺手**：宁可多想一种没见过的公司形态（门店×单店、用户×ARPU、保费×综合成本率、产能滞后链…），也不要为当前这家省事而收窄通用性。
- 这条统领下面的所有原则与所有 skill；两个 skill 里反复出现的"不要拿牛奶的行名套别的公司"就是它的具体落地。

## 🔴 项目第一原则（理解项目必须先懂这条）

**TuShare 数据缺口 = 用 reconciler 去年报里拉干净。这是本项目存在的根本理由。**

当 `clean.py` 年度硬校验出现 `target_gt_calc`（合计 > 明细和，即 TuShare 漏披露某明细科目）时，**正确的解法不是放弃、不是人工、不是季度式 plug 收纳，而是 `annual_report_reconciler.py` 去对应年报 Markdown 里把缺失的明细金额找回来**，LLM 高置信确认残差后生成 approved override，重跑 `clean.py` 应用补全。

- `raw_tushare` 永不被修改；补全只进年度 clean 宽表，并写入 `clean_adjustments`/`clean_warnings` 审计，全程可追溯。
- 美的集团 `lending_funds`（发放贷款和垫款）、比亚迪 BS 3.1 流动负债缺明细，都是这一类，都由 reconciler 解决。
- 遇到 `target_gt_calc` 类年度缺口，**默认动作就是让 reconciler 拉年报补全**，不要问"要不要保持失败/要不要人工"——那是对项目使命的误解。
- 唯一例外：`target_lt_calc`（明细和 > 合计，即 clean.py 自己重复计数/误分类），这是 clean.py 的 bug，应修字段分类，**不是** reconciler 的活。

## 技术栈

- **语言**: Python 3.11+（系统全局 Python，禁止 venv）
- **依赖**: `tushare>=1.4.0`, `pandas>=2.0.0`, `requests>=2.31`, `pymupdf>=1.24`（见 `requirements.txt`）
- **存储**: SQLite（每家公司一个 `data.db`，路径 `companies/{公司名}_{代码}/Agent/data.db`）
- **数据源**: TuShare Pro API，经中转站 `fastapic.stockai888.top` 代理；巨潮资讯网 cninfo 用于年报 PDF + Markdown 下载

## 项目结构

```
MKA/
├── src/                      # 核心 Python 源码
│   ├── __init__.py
│   ├── init.py               # 一键编排入口
│   ├── data_fetcher.py       # 阶段①：TuShare拉取+标准化+入库（~1250行）
│   ├── clean.py              # 阶段②：EAV→宽表+配平校验+SQLite clean表写入
│   ├── field_registry.py     # field_registry.yaml loader:三表字段元数据唯一真源
│   ├── field_registry.yaml   # 全程序会计科目唯一真源(分类/会计序/标签/resolve/sign);clean.py 校验 + workbench 渲染 + 数据格式参考.md 同源
│   ├── report_downloader.py  # 巨潮资讯网年报 PDF + Markdown 批量下载
│   ├── annual_report_utils.py     # 年报 Markdown/LLM 公共工具（reconciler / analyzer 共用）
│   ├── annual_report_reconciler.py # clean.py 年度硬校验失败后的年报 Markdown 智能核对
│   ├── annual_report_extractor.py  # 年报 Markdown LLM 萃取
│   ├── financial_expense_analyzer.py # 财务费用附注细则分析 → financial_expense.yaml（多年档案）
│   ├── defaults_gen.py       # clean_annual/meta → defaults.yaml
│   ├── yaml1_cleaner.py      # yaml1 + defaults.yaml → 内部 forecast params + report
│   ├── forecast.py           # 正式入口：defaults.yaml + yaml1*.yaml → Agent/forecast/
│   ├── calc.py               # 标准参数表 → 预测三表 + DCF
│   └── yaml2_schema.py       # YAML2 读写与校验
├── docs/                     # 项目文档
│   ├── ARCHITECTURE.md       # 系统架构文档（当前状态描述，每次开发完必须更新）
│   ├── CHANGELOG.md          # 里程碑变更日志（从 ARCHITECTURE 第11节分离，按日期倒序追加）
│   ├── CLAUDE.md             # 项目约定与关键规则
│   └── ...
├── requirements.txt          # Python依赖
├── .env                      # TUSHARE_TOKEN / HTTP_URL / 限速间隔
├── companies/                # 输出目录，每公司一个子目录
│   └── {公司名}_{代码}/
│       ├── 公司判断和最新观点.md
│       ├── Agent业务讨论.md   # /brkd 产出：业务预理解参考
│       ├── *核心假设*.md
│       ├── active_vore/      # 活跃收集，外部模型和当前材料，不移动
│       │   ├── 核心假设生成（模型放在这里）/  # /ka 读取外部模型
│       │   └── 业务理解器（研报和纪要放在这里）/ # /brkd 读取研报/纪要
│       ├── WEBCLAUDE/        # 高频打包区，供网页 Claude 上传使用
│       ├── 公告/
│       │   ├── 年报/         # 年度报告 PDF + Markdown
│       │   ├── 季报/         # 季报/半年报 PDF + Markdown
│       │   └── 临时公告/
│       ├── 研报/
│       ├── 纪要/
│       ├── 收集/
│       ├── 重要文件/
│       └── Agent/            # 建模 Agent 运行区
│           ├── data.db       # SQLite（raw_tushare/meta/clean_annual/clean_quarterly）
│           ├── defaults.yaml # 唯一 YAML2：机器平推底座
│           ├── financial_expense.yaml
│           ├── yaml1*.yaml   # compiler 输出：人的判断覆盖层
│           ├── recon/        # 年报核对 evidence JSON
│           ├── .modelking/   # 内部编译产物，不作为人工维护界面
│           └── forecast/     # 唯一正式 DCF 输出，每次重算先清空再生成
├── vendor/
│   └── use_cninfo/           # vendored rollysys/use_cninfo（MIT）
└── .refs/                    # TuShare官方文档缓存
    ├── tushare-docs/         # 32.md(daily_basic), 33.md(income), 36.md(balancesheet), 44.md(cashflow), 79.md(fina_indicator)
    └── tushare-data/         # TuShare SDK技能参考
```

## 数据流水线

```
TuShare API
    ↓ data_fetcher.py（阶段①）
companies/{公司名}_{代码}/Agent/data.db
  ├── raw_tushare      (EAV: ticker, endpoint, report_type, end_date, field, value, ...)
  ├── meta             (KV: key, value)
  ├── clean_annual     (wide: period + 325 official fields + 6 QA plug fields)
  ├── clean_quarterly  (wide: period + 325 official fields + 6 QA plug fields)
  ├── clean_adjustments
  └── clean_warnings
    ↓ clean.py（阶段②）
SQLite data.db: clean_annual / clean_quarterly
  （宽表：行=period，列=统一 331 数据字段，严格配平并保留 warning）
    ↓ financial_expense_analyzer.py（可选增强）
companies/{公司名}_{代码}/Agent/financial_expense.yaml
  （按年份归档的年报财务费用附注拆解：components / derived / checks / status）
    ↓ defaults_gen.py
companies/{公司名}_{代码}/Agent/defaults.yaml
  （唯一 YAML2：完整、配平、无判断的机器平推底座；financial_expense 可能来自 annual_report.fin_exp_note）
    ↓ forecast.py：yaml1*.yaml + defaults.yaml
companies/{公司名}_{代码}/Agent/forecast/
  （唯一正式 DCF 输出；中间参数/报告写入 Agent/.modelking/）
```

## 建模三站管线（/brkd → /ka → /comp）

取数流水线之外，建模有三个串行 skill 站：

```text
研报/纪要 → /brkd → Agent业务讨论.md → /ka → 核心假设.md → /comp → yaml1
            读懂        记全              译准
         discernment   fidelity         翻译
```

- `/brkd`（业务预理解器）：读 `active_vore/业务理解器（研报和纪要放在这里）/` 下的研报和纪要，产出 `Agent业务讨论.md`（公司根目录），作为 `/ka` 的业务预理解参考。
- `/ka`（核心假设生成）：消费 `Agent业务讨论.md` + `active_vore/核心假设生成（模型放在这里）/` 中的外部模型，产出 `*核心假设*.md`。
- `/comp`（yaml1 编译器）：把 `核心假设.md` 编译为 `yaml1*.yaml`。

## DCF 运行规则（必须遵守）

用户视角只需要维护两类输入：`defaults.yaml`（YAML2，机器平推底座）和 `yaml1*.yaml`（compiler 输出，人的判断覆盖层）。正式运行命令：

```bash
py -m src.forecast --ticker 002946.SZ
```

这条命令内部执行 `yaml1_cleaner.py` 的 fold / expand / resolve / backtest，再把标准参数交给 `calc.py`。默认只在 `Agent/forecast/` 暴露最终结果：

```text
companies/{公司名}_{代码}/Agent/forecast/
```

中间产物是内部编译缓存，默认写入：

```text
companies/{公司名}_{代码}/Agent/.modelking/forecast_params.yaml
companies/{公司名}_{代码}/Agent/.modelking/yaml1_clean_report.json
```

不要在公司目录顶层生成或维护 `yaml2_yearly.yaml`、`forecast_params.yaml`、`yaml1_clean_report.json`。`defaults.yaml` 是唯一 YAML2；清洗后的逐年标准参数表不是 YAML2。正式输出目录只能是 `Agent/forecast/`，每次重算必须先清空旧 `Agent/forecast/` 再生成，禁止用 `forecast_current/forecast_fixed/forecast_yaml1` 这类目录承载正式结果。

`calc.py` 是纯算账核/回归工具，只接受 `--forecast-params` 参数（清洗后的逐年标准参数表，如 `Agent/.modelking/forecast_params.yaml`），永远看不到 yaml1，也不直接读取 `defaults.yaml`。`defaults.yaml` 进入 `calc.py` 的唯一合法路径是先经过 `yaml1_cleaner.py`（无 yaml1 时用 `--defaults-only` 做恒等清洗）。有 yaml1 的公司请走正式入口 `py -m src.forecast --ticker ...`。

**capex 路由前提**：`balance_sheet.capex_pct` 必须是合并口径（`c_pay_acq_const_fiolta / revenue`，defaults_gen 默认产出）。`calc.py` 据此把 PP&E 份（`capex − Σ三项摊销`）灌进 `fix_assets`；若 yaml1 把 `capex_pct` 改成固定资产口径会双重扣减，且无自动守卫。

## 本地 Web 工作台（FastAPI + React）

ModelKing 前端是本地文件工作台：把 `companies/{公司名}_{代码}/` 映射为一家公司的一页。第一版只读展示 + 一键重算，不直接改写核心假设或 yaml1。工作台不是新的建模入口，重算按钮必须调用 `src.forecast`，仍遵守 `defaults.yaml + yaml1*.yaml -> Agent/forecast/`。

```bash
npm install
npm run build          # 验证 React/Vite 前端
py -m src.workbench    # 启动 FastAPI，并打开 http://127.0.0.1:8765
```

Windows 双击入口是 `run_workbench.cmd`。开发前端时可单独跑 `npm run dev`，但正式预览/日常使用走 `py -m src.workbench`。

前端目录：

```text
app/                   # React + Vite UI
src/workbench.py       # FastAPI 本地壳，读 companies/ 并调用 src.forecast
```

工作台必须保持 Apple HIG / SF Pro 风格：白与 #F5F5F7 灰底、#1D1D1F 主文字、#0071E3 只用于交互、无渐变、无装饰图标。表格是高风险区域：数字右对齐、SF Mono、负数 #FF3B30、轻 zebra、表头 11px all-caps。YAML 面板是唯一允许多语法色的区域，按 Xcode source editor 处理。

**前端完整设计规范见 `docs/前端设计规范.md`，改前端前必读。** 那份是权威，本节只是速记。注意：实际色值以 `app/src/styles.css` 的 CSS 变量为准（`--blue:#003d7a`、`--red:#b42318`，与上面 `#0071E3/#FF3B30` 不符——上面是设计意向，落地用 CSS 变量）。规范里已固化的关键偏好：五个 tab 固定顺序（Overview / 核心假设展示 / 完整三表 / DCF / Materials，不开单独 Core Assumption、估值桥常驻 DCF 不做子页签）；三表行序严格按会计准则序（`STATEMENT_META.field_order` 覆盖字母序，绝不按字段名字母序展示）；减项标签统一 `减:` 前缀（`LABEL_OVERRIDE` 维护，如 `减:研发费用`/`减:信用减值损失`）；年份表头纯黑底白字 + 预测年份带 E 后缀；历史|预测分界用 2px 蓝竖线（不用灰底/白底色块）；不展示 raw 字段列；完整三表范围开关「近5年+预测(默认，仅显式预测期到 `terminal.explicit_end`，fade 期隐藏)/完整历史」；stash 参考项按 JSON 结构类型分派（6 类+兜底，不按公司名特判，零丢失）；敏感性数值 ≤20px 不挤占主表。禁忌清单与改动纪律（重启 workbench 前先杀 8765 僵尸进程）详见规范文档。

## 年报 PDF + Markdown 下载 report_downloader.py

直接复用 `vendor/use_cninfo/src/cninfo` 中的 cninfo API 封装，只在项目根目录维护一个业务薄脚本。

### CLI

```bash
python -m src.report_downloader --ticker 000333.SZ
python -m src.report_downloader --ticker 000333.SZ --list-only
python -m src.report_downloader --ticker 000333.SZ --force-markdown
python -m src.report_downloader --ticker 000333.SZ --no-markdown
```

### 输出与规则

- 输出目录：`companies/{公司名}_{代码}/公告/年报/`
- 文件名：`{年份}_年度报告.pdf`；修订版为 `{年份}_年度报告_修订版.pdf`
- Markdown 文件与 PDF 同名：`{年份}_年度报告.md`；修订版为 `{年份}_年度报告_修订版.md`
- Markdown 默认生成，内容包含 YAML frontmatter + PyMuPDF 提取全文
- 只保留 `YYYY年年度报告` 和 `YYYY年年度报告（修订版）`
- 排除 `年度报告摘要`、英文版、英文全文、摘要更新/取消等非中文年报本体
- 按年份从新到旧排序，同年份修订版优先
- 已存在 PDF/Markdown 分别跳过，不重复下载或抽取
- 默认 cninfo 请求/PDF 下载间隔 1-2 秒

### 已验证样例

```bash
python -m src.report_downloader --ticker 000333.SZ
```

美的集团（000333.SZ）实测下载 2013-2025 共 13 份中文年度报告 PDF，并生成 13 份同名 Markdown，其中 2016-2025 全部成功；二次运行 `pdf_downloaded=0, pdf_skipped=13, md_written=0, md_skipped=13`。

## 年报 Markdown 智能核对 annual_report_reconciler.py

这是 `clean.py` 的外置补全/诊断能力，只在年度硬校验失败且本地已有年报 Markdown 时使用。脚本复用 `clean.py` 的年度透视、字段分类、combo resolve、`apply_annual_income_subtotal_adaptations` 与 `check_*()` 校验函数收集失败（**与 clean.py 主流程 adaptation→overrides→check 顺序对齐**，确保 reconciler 看到的失败 = clean.py 实际会遇到的失败），再切出对应年报片段，必要时调用配置好的 LLM（默认 GLM `glm-5.2`）输出结构化 evidence。它不修改 `data.db`、`raw_tushare`、`clean_annual` 或 `clean_quarterly`。

**LLM 模型与两层 fallback（2026-06-18）**：`GLM_MODEL=glm-5.2`（智谱官方 API，裸串；`[1m]` 只是 Claude Code 显示标签非 API 参数）。glm-5.2 是推理模型，`call_llm` 对 model 含 "5.2" 自动发 `thinking:{"type":"disabled"}`——否则它烧 reasoning_tokens 导致 max_tokens 截断返回空（`GLM_THINKING=enabled` 可覆写）；glm-5-turbo/glm-4-long 不受影响。补全走两层：① rule-first（`rule_based_override_suggestions` 别名+金额正则组合 + Phase B LLM 确认，精确便宜）；② rule 未闭合的残余进 `_llm_propose_fallback`，用 `full_context=True`（statement snippet 不截、总额 200K，让 NCA/权益尾部可见）让 LLM 提议缺失字段，复用 Phase A 已抽 context。防脏配平闸门：提议必须 `recommended_action=="add_override"`（LLM 自判 fix_classification/manual_review 不批）、提议字段必须在 failure 的 candidate 字段集内（挡 LLM 编造字段名）、`|残差差|<TOLERANCE`。429 用 30/60/90s 长退避（GLM 按分钟限流，短退避会把整片静默吞成"无提议"假阴性）；fallback 并发降到 3。紫金矿业实测：25 approved override，年度 clean 仍剩 4 硬失败（BS 2.1 2025 多字段缺口、BS 2.2 2020/2024/2025 jumbled 文本找不到单一吻合项 + 2024 缺 cninfo 年报）——与 glm-5-turbo 基线一致，fallback 未突破这 4 个但守卫正确拒绝脏配平。

**三层防脏 override 守卫（2026-06-18，贵州茅台 600519 驱动）**：reconciler 曾对 IS 1.1（营业总成本）造脏 override——LLM 把年报"信用减值损失"值（≈残差量级的负数）塞给 `total_cogs` 这个 subtotal 字段本身，clean 应用后覆盖了 adaptation 已修好的明细和，反而制造 IS 1.1 失败。三层防御：① **`failure_candidate_fields` 所有 IS/CF 分支排除 `"subtotal"`**——subtotal（total_cogs/total_opcost/operate_profit/total_profit/n_income/total_revenue 等被校验汇总目标）不是待补明细，纳入 candidate 即允许改写校验目标=脏配平（BS 走 `bs_fields_for_bucket` 本就不含 subtotal）；② **reconciler `collect_failures` 前先跑 `apply_annual_income_subtotal_adaptations`**——IS 1.1 的 official total_cogs vs 明细和小残差本就被 adaptation 兜底，不再误报为 failure、不进 LLM fallback；③ **`_llm_propose_fallback` 的 `add_override` 拒绝非 0 `old_value`**（与 `rule_based_override_suggestions` 既有守卫对齐）——add_override 只补漏录/为 0 字段，不得覆盖已有非 0 值。茅台删 3 条脏 override 后 clean 年度 10 期+季度 48 期全过；重跑 reconciler `--no-llm` 0 failure。

### CLI

```bash
python -m src.annual_report_reconciler --ticker 000333.SZ
python -m src.annual_report_reconciler --ticker 000333.SZ --only-year 2025 --only-code "BS 2.1"
python -m src.annual_report_reconciler --ticker 000333.SZ --no-llm
python -m src.annual_report_reconciler --ticker 000333.SZ --write-overrides --approve-high-confidence
```

输出目录：`companies/{公司名}_{代码}/Agent/recon/`，包含时间戳 JSON、`annual_report_reconciliation_latest.json`，以及可选的 `annual_report_overrides.json`。

`annual_report_overrides.json` 必须由 LLM 结构化结论生成；`--write-overrides` 与 `--no-llm` 互斥。`clean.py` 只应用 `annual_report_overrides.json` 中 `status=approved` 且 `source` 为 approved LLM provider（当前 `glm`，历史 `kimi` 仍兼容）的记录，且只应用到年度 clean 宽表；每条应用记录写入 `clean_adjustments`，补数 warning 和软校验 warning 写入 `clean_warnings`。

美的集团（000333.SZ）2016-2025 年 `BS 2.1` 实测：生成 10 条 approved `lending_funds` 补数；`python -m src.clean --ticker 000333.SZ --mode annual` 后年度 10 期全部硬校验通过。

### 年度 hard-check 强触发

当 `clean.py` 在 annual 或 all 模式下遇到年度 hard check 失败，必须把它当作 clean-data blocker：这不是 soft warning，当前年度 clean 输出不能被信任。默认行为是自动调用：

> **2010 闸门**：强触发与年报核对只对 **2010 年及以后**的年度硬校验失败生效。`clean.py` 把 2010 之前年度的硬校验失败**降级为 warning 直接入库**（写进 `clean_annual`，不阻塞、不触发 reconciler）；`annual_report_reconciler.py` 的 `collect_failures` 也跳过 2010 之前的年度。原因：A 股 2010 前披露稀疏、格式早期，对年报核对得不偿失。`RECONCILE_MIN_YEAR=2010` 是 clean.py 的唯一闸门常量。

```bash
python -m src.annual_report_reconciler --ticker {ticker} --db {data.db} --max-failures 20 --write-overrides --approve-high-confidence
```

终端要清楚告诉用户：哪里失败导致 clean 停止；系统正在用本地年报 Markdown + LLM evidence 判断是否为 TuShare 字段缺失/口径问题；`raw_tushare` 不会被修改；本次失败运行不会被改判成功。若 LLM 生成新的 approved override，用户重跑 `clean.py` 后才会由正常流程应用补数，并写入 `clean_adjustments`/`clean_warnings`。

可用 `--no-auto-reconcile` 关闭强触发，用 `--auto-reconcile-max-failures N` 控制自动分析条数。`annual_report_reconciler.py` 写默认 override 文件时会合并旧记录，不能覆盖掉已有 approved LLM 证据。

### 两轮补数 + 年度 plug 兜底（init.py 编排，2026-06-18）

`init.py` 的 `stage_clean` 把年度补全做成**两轮 + plug 兜底**（`MAX_BACKFILL_CYCLES=2`）：

1. **第一轮**：clean 失败 → 内部强触发 reconciler（rule + LLM fallback）提议 override。
2. **第二轮（核对第一轮）**：reconciler 在 `collect_failures` 前先用 `clean.load_approved_overrides`+`apply_annual_overrides` 应用已有 approved override——第二次跑天然只见第一轮补完后的残差，LLM 在 field_context 看到 round 1 已补的值、专攻更小残差。每轮 = 应用新 override 重跑 clean +（非末轮）再强触发 reconciler。
3. **两轮都不过 → plug 提示**：`_offer_annual_plug` 交互问用户是否对残余硬失败塞年度 QA plug。用户同意 → 写 `companies/{公司}/Agent/recon/annual_plugs.json`（`period` 为**纯年份**，匹配 annual wide.index）→ 重跑 `clean.py --mode annual --allow-annual-plug`。

`clean.py` 年度 plug：`apply_annual_bs_plugs`（镜像季度 `apply_quarterly_bs_plugs`，但**只在用户指令的 (period, code) 生效**，非自动全期）+ `--allow-annual-plug` flag + `load_annual_plugs`/`default_plugs_path`。`bs_bucket_sum` 已含 `qa_bs_*_plug` 故 check_bs 自动吸收残差；写 `annual_bs_plug` warning（带公式 + "硬问题 plug，非披露不完整" + 建议人工核对后改用 LLM override 并删 plug）。年度 plug 是诚实逃生通道，不是常规兜底——关键科目建议拒绝 plug、如实留 exit 3。

`_run_clean` 捕获 stderr 解析 `HARD CHECK FAIL: BS 2.2 2020 ... residual=...` 行，供 plug 提示向用户展示确切残差。

## 季度 QA plug 收纳科目

季度报告明细披露弱于年报，`clean.py` 在 quarterly 模式下允许用显式 QA plug 字段吸收 BS bucket 小计残差：

- `qa_bs_current_asset_plug`
- `qa_bs_noncurrent_asset_plug`
- `qa_bs_current_liab_plug`
- `qa_bs_noncurrent_liab_plug`
- `qa_bs_equity_plug`
- `qa_cf_cash_reconcile_plug`

这些不是 TuShare 官方字段，只是 clean 审计字段。年度/季度 clean 表都保留 325 个官方字段 + 6 个 QA plug 字段，保证 schema 统一；年度 plug 正常为 0。季度 BS plug 只参与 BS 2.1/2.2/3.1/3.2/4.1 bucket 小计校验；`qa_cf_cash_reconcile_plug` 只参与 CF 5.5 期初期末现金桥接，不参与 CF 5.1-5.4 的流量明细加总；不修改 `raw_tushare`。

使用 plug 时必须透明：`clean_warnings` 的 `quarterly_bs_plug` / `quarterly_cf_cash_plug` 记录要写清楚哪里合不上、目标值、计算值、残差、使用哪个 plug 字段，以及建议检查对应季报/半年报/三季报。美的集团（000333.SZ）季度实测 48 期全部硬校验通过，仅 `BS 2.1` 使用 `qa_bs_current_asset_plug`。

## 已知 TuShare 缺陷提示卡

`knowledge/known_tushare_defects.json` 是给 `annual_report_reconciler.py` 的轻量 LLM 检索提示，不是补丁库。索引用“触发条件 + 字段”，不要用公司名；命中后只把 hint 写入 reconciliation JSON 并加入年报 Markdown 检索词。

当前条目：
1. `BS 2.1` / `balancesheet` / `current_asset` / `receiv_financing`（格力电器 2019-2025）：`total_cur_assets` 大于流动资产明细和且 `receiv_financing` 缺失/为 0 时，提示 LLM 查“应收款项融资”（2019 新金融工具准则新增行项目）。
2. `BS 2.1` / `balancesheet` / `current_asset` / `lending_funds`（美的集团 2016-2025）：`total_cur_assets` 大于流动资产明细和且 `lending_funds` 缺失/为 0 时，提示 LLM 查“发放贷款和垫款 / 发放贷款 / 垫款 / 贷款”。
3. `BS 3.1` / `balancesheet` / `current_liab` / `estimated_liab`（比亚迪 2016-2025）：`total_cur_liab` 大于流动负债明细和且 `estimated_liab` 缺失/为 0 时，提示 LLM 查流动负债段的“预计负债-流动 / 预计负债”。该条带 `clean_category=current_liab`：TuShare 只有一个 `estimated_liab` 字段且默认按非流动归类，当公司把预计负债列在流动负债时，override 用 `clean_category` 把补数在本期重分类到流动负债 bucket（见下「override clean_category 重分类」）。
4. **NCA/NCL 新准则科目（最常见、跨公司系统性漏录）**——`BS 2.2` 非流动资产 / `BS 3.2` 非流动负债 `target_gt_calc` 失败时优先查这几个字段，TuShare 对它们按公司全年留空，年报却披露了：
   - `BS 2.2` / `noncurrent_asset` / `oth_eq_invest`（其他权益工具投资，2017 新金融工具准则，A+H 2018 起执行）
   - `BS 2.2` / `noncurrent_asset` / `oth_illiq_fin_assets`（其他非流动金融资产，同上）
   - `BS 2.2` / `noncurrent_asset` / `use_right_assets`（使用权资产，新租赁准则，A+H 2019 起执行；房地产/租赁密集公司体量数百亿）
   - `BS 3.2` / `noncurrent_liab` / `lease_liab`（租赁负债，新租赁准则，与 `use_right_assets` 成对出现；取非流动部分，流动部分在“一年内到期的非流动负债”勿重复计）
   - 2018/2019 前这些科目真值为 0（准则未生效），TuShare 的 NULL 恰好≈真值不产生残差；故 BS 2.2 失败从 2018、BS 3.2 从 2019 起。单字段闭合不了时考虑 2-3 项之和（如紫金 BS 2.2 2025 = 三项联合闭合）。确认案例：万科A 000002（2018-2025）、紫金矿业 601899。

这些来自确认案例，但不能作为自动补数依据，仍须年报片段金额 + LLM high confidence 确认。

**另一类 TuShare 口径问题（clean.py 内修复，不进提示卡）**：TuShare balancesheet `total_share` 是**股数（百万股）**，不是股本(元)，且无独立股本(元)字段。clean.py 权益 bucket 求和需用股本(元)，故 `infer_par_value` 按权益恒等式跨年推断面值（离散法定常量 1/0.1/0.5/...，平票归 1.0），`check_bs` 的 BS 4.1 按 `股本(元)=par×total_share` 折算参与求和——**仅校验折算，`total_share` 存储值不变**（下游每股计算仍用股数）。面值 1 元公司 par=1.0 零影响；面值≠1（如紫金矿业 0.1）由此配平。属 target_lt_calc 的 clean.py 字段口径修复，不走 reconciler。

### override clean_category 重分类（处理 TuShare 字段归类与公司列报口径不一致）

部分 TuShare 字段的 bucket 归属对个别公司不成立（典型：`estimated_liab` 预计负债，TuShare 默认非流动，但比亚迪列报为流动）。这类情况**不能改 clean.py 的静态分类**（会破坏其他公司），而是由 reconciler 在 override 记录里写 `clean_category`，`clean.py` 应用时只对**该公司该期**把字段重分类到目标 bucket（写入 `wide.attrs["bs_reclass"]`，`bs_bucket_sum` 按 `reclass.get(field, 静态分类)` 取 bucket）。字段值照常补进宽表（下游可见），bucket 加总落到正确的一侧。`clean_adjustments` 记录 `clean_category` 审计。

重要边界：known defect hint 只是“去哪查”的线索；approved override 仍必须靠年报片段金额解释残差，并由 LLM high confidence 结构化确认。

## 阶段① 核心模块 data_fetcher.py

### 公共 API

```python
fetch_company("600519.SH", force_refresh=False) -> str   # 返回 SQLite 文件路径
fetch_companies(["600519.SH", "300866.SZ"]) -> dict       # 批量拉取
```

### CLI

```bash
python -m src.data_fetcher --ticker 300866.SZ          # 拉取
python -m src.data_fetcher --ticker 300866.SZ --force   # 强制刷新（清空旧数据后重拉）
python -m src.data_fetcher --ticker 300866.SZ --verbose # 调试日志
```

### 关键类与函数

| 名称 | 用途 |
|------|------|
| `TushareDataFetcher` | 核心拉取类，管理 TuShare 客户端、限速、缓存 |
| `convert_value(value, unit)` | 单位转换（元→百万元、%→小数、万股→百万股等） |
| `official_statement_mappings(endpoint)` | 从官方文档解析完整字段映射 |
| `records_for_quarterly_flow()` | 流量表季度拆算（Q2=H1-Q1, Q3=Q3cum-H1, Q4=年报-Q3cum） |
| `records_for_quarterly_point()` | 存量表直接入季度（资产负债表不做拆算） |
| `validate_records_before_write()` | 入库前硬健康检查 |
| `run_quality_checks()` | 入库后勾稽校验（BS配平、现金流勾稽、季度加总） |

## 阶段② 核心模块 clean.py

### 公共 API

```python
clean("D:\\MKA\\companies\\某公司_002946\\Agent\\data.db", "002946.SZ") -> pd.DataFrame
```

### CLI

```bash
python -m src.clean --ticker 002946.SZ          # 自动定位 data.db 并清洗
python -m src.clean --ticker 002946.SZ --db path/to/Agent/data.db  # 指定 db
python -m src.clean --ticker 000333.SZ --mode annual          # 只生成年度 clean 表
python -m src.clean --ticker 000333.SZ --mode quarterly       # 只生成季度 clean 表，必要时写显式 QA plug warning
python -m src.clean --ticker 000333.SZ --no-overrides         # 不应用 approved 年报补数
python -m src.clean --ticker 000333.SZ --mode annual --no-auto-reconcile  # 年度失败时不自动触发年报核对
python -m src.clean --ticker 002946.SZ --verbose              # 调试日志
```

### 关键函数

| 名称 | 用途 |
|------|------|
| `load_raw_tushare()` | 读取 EAV，过滤 report_type=1, comp_type=1 |
| `dedupe_by_f_ann_date()` | 同 (endpoint, end_date, field) 取 f_ann_date 最晚 |
| `pivot_to_wide()` | EAV→宽表，处理跨端点同名字段（如 credit_impa_loss 加前缀消歧），**补全全 NaN 列和 QA plug 列，确保所有公司输出相同列集** |
| `apply_quarterly_bs_plugs()` | 季度 BS bucket 小计残差收纳到显式 `qa_bs_*_plug`，并写入公式级 `clean_warnings` |
| `apply_quarterly_cf_cash_plugs()` | 季度 CF 5.5 期初期末现金桥接残差收纳到 `qa_cf_cash_reconcile_plug`，并写入公式级 `clean_warnings` |
| `resolve()` | 合并科目处理（公司只报合并项时自动适配，如 accounts_receiv_bill） |
| `check_is()` | 利润表硬校验（营业总成本/营业利润/利润总额/净利润/归属/综合收益） |
| `check_bs()` | 资产负债表硬校验（流动/非流动资产/负债、权益明细、终极配平） |
| `check_cf()` | 现金流量表硬校验（三大活动、汇总、期初期末） |
| `check_is_supplement()` | IS 补充校验（综合收益归属、持续/终止经营） |
| `check_cross_table()` | 跨表硬校验（IS净利润=CF附注净利润） |
| `check_soft()` | 软校验仅警告（财务费用差异、现金vs货币资金、方向/量级合理性） |

### 校验层级

- **硬校验**（`CheckError` 报错停止）：IS 1.1-1.6, BS 2.1-4.3, CF 5.1-5.5, IS补充 6.1-6.3, 跨表 7.1, 逐年连续性 7.4；季度 BS bucket 小计残差和 CF 5.5 现金桥接残差先进入显式 QA plug 并写 warning，plug 后仍不平才停止
- **软校验**（仅 warning）：跨表 7.2-7.3, 方向合理性 10.1, 量级合理性 10.2, 折旧vs固定资产 10.3, 毛利率范围 10.4
- **容差**：残差 < 1（百万元）
- **年度失败处理**：annual hard check 失败会默认强触发 `annual_report_reconciler.py`；这只生成 evidence/override，不修改 raw，不静默放行 clean

### 合并科目 resolve 规则

部分公司只报合并项，部分报拆分项，`resolve()` 自动适配：

| 合并项 | 拆分项 |
|--------|--------|
| `accounts_receiv_bill` | `notes_receiv` + `accounts_receiv` |
| `oth_rcv_total` | `oth_receiv` |
| `fix_assets_total` | `fix_assets` |
| `cip_total` | `cip` |
| `accounts_pay` | `notes_payable` + `acct_payable` |
| `oth_pay_total` | `oth_payable` |
| `long_pay_total` | `lt_payable` |

## SQLite Schema

| 表 | 主键 | 说明 |
|----|------|------|
| `raw_tushare` | (ticker, endpoint, report_type, end_date, field) | TuShare原始镜像，完整保留官方字段 |
| `meta` | key | 公司元信息（ticker, name, total_share, total_mv 等） |
| `clean_annual` | period | 年度 clean 宽表：325 个 TuShare 官方字段 + 6 个 QA plug 字段 |
| `clean_quarterly` | period | 季度 clean 宽表：325 个 TuShare 官方字段 + 6 个 QA plug 字段 |
| `clean_adjustments` | 无 | clean 阶段应用的 approved 年报补数审计记录，不修改 raw_tushare |
| `clean_warnings` | 无 | clean 阶段 warning 记录，包含补数 warning 和软校验 warning |

## 关键约定（修改代码时必须遵守）

### 字段命名
- **只用 TuShare 官方字段名**，如 `n_income_attr_p`、`total_hldr_eqy_inc_min_int`、`c_pay_acq_const_fiolta`；唯一例外是 clean 阶段的 6 个 `qa_*_plug` 审计字段
- **禁止使用任何内部别名**，`field_terms.csv` 和 `statement_field_coverage.csv` 中不得出现非官方字段

### 会计科目与排序的唯一真源:field_registry（2026-06-22 改版）
三表 325 个官方字段的元数据——**哪张表 / 哪个 bucket / 第几行(会计序) / 中文标签 / 是否小计 / resolve 父子 / 符号语义**——全部声明在 `src/field_registry.yaml` 一处。`clean.py` 的 `IS/BS/CF_FIELD_CATEGORIES`、`IS/BS_SUB_RESOLVE`、`COMBO_RESOLVE`、`SIGN_QUESTIONABLE_IS_FIELDS` 与 `workbench.py` 的三表渲染排序/标签都 `from .field_registry import`，`docs/数据格式参考.md` 由 `scripts/gen_field_reference.py` 从它派生。改一处,校验+前端+文档同步,不再有并行声明漂移。
- **flat 有序列表 = 会计序**:`statements.<income/balancesheet/cashflow>.fields` 的列表顺序即会计准则序=前端展示序。`category_order`(展示桶序,不含 subtotal)+ `category_labels`(全 category→中文,含 subtotal)分离声明。小计字段(category=subtotal)在列表中的位置即其展示位置,不再用 `subtotal_after` 单独挂载。
- **label 直接带"减:/其中:"前缀**,`LABEL_OVERRIDE` 已溶解。三个 BS 总计(`total_assets`/`total_liab`/`total_liab_hldr_eqy`)标 `role: total`。
- **改字段分类/排序**:直接编辑 `field_registry.yaml`。`tests/test_field_registry.py` 守内部一致性(字段数/标签覆盖/resolve 引用/combo 拆项同桶/total_fields)。
- **改版修了 stale drift**:`credit_impa_loss`/`assets_impair_loss`/`oth_impair_loss_assets` 旧 `数据格式参考.md` 误标 `cost_item`,实际 clean.py 校验为 `operating_adjustment`;registry 统一为 `operating_adjustment`,文档同步修正。
- `check_is/bs/cf` 的 subtotal 公式仍写在代码里(B1:元数据同源,公式不数据驱动);`known_tushare_defects.json` 独立保留,未并入。

### 单位转换（入库单位）
| 类别 | 入库单位 | 转换 |
|------|----------|------|
| `amount_cny` | 百万元 | 元 ÷ 1,000,000 |
| `percent` | 小数 | 原值 ÷ 100（如 roe=15.5 → 0.155） |
| `share` | 百万股 | 股 ÷ 1,000,000 |
| `daily_basic_share_10k` | 百万股 | 万股 ÷ 100 |
| `daily_basic_mv_10k_cny` | 百万元 | 万元 ÷ 100 |
| `turnover_rate` | 天 | 365 ÷ 周转率 |
| `ratio` / `price` | 原值 | 不转换 |

### 去重规则（同一 end_date 多条记录时）
1. `report_type = '1'`（合并报表）
2. `comp_type = '1'`（一般工商业，非此则跳过并 warning）
3. 优先 `update_flag = '1'`
4. 再取 `f_ann_date` 最晚 → `ann_date` 最晚

### 健康检查（硬校验，不通过则拒绝入库）
1. 三张表至少各有一批记录
2. 主键无重复
3. ticker 与请求一致
4. `raw_tushare` 每端点每报告期必须覆盖官方全部数值字段
5. 最新年度核心字段不得缺失（revenue, n_income_attr_p, total_assets, total_liab, total_hldr_eqy_inc_min_int, n_cashflow_act 等）
6. meta 必须包含 ticker, name, latest_trade_date, total_share, total_mv
7. BS 配平：total_assets ≈ total_liab + total_hldr_eqy_inc_min_int（容差 0.01）
8. 现金流勾稽：CFO+CFI+CFF+汇兑 ≈ 现金净增（容差 0.01）
9. 季度加总：Q1+Q2+Q3+Q4 = 年报值（容差 0.01）

### 限速与重试
- 默认每次请求后等待 0.8s（约 75次/分钟，低于中转站 100次/分钟限额）
- 限频错误等待 60s 后重试，最多 3 次
- 鉴权/权限错误直接抛出，不重试

## 官方文档字段数量（校验基准）

| endpoint | 数值字段数 | 本地文档 |
|----------|-----------|----------|
| `income` | 86 | `.refs/tushare-docs/33.md` |
| `balancesheet` | 150 | `.refs/tushare-docs/36.md` |
| `cashflow` | 89 | `.refs/tushare-docs/44.md` |

## 验收方式

```bash
# 1. 语法检查
py -m py_compile src/data_fetcher.py
py -m py_compile src/clean.py
py -m py_compile src/report_downloader.py

# 2. 阶段①：拉取
py -m src.data_fetcher --ticker 300866.SZ --force --verbose

# 3. 阶段②：清洗+配平校验
py -m src.clean --ticker 300866.SZ --verbose

# 4. 年报 PDF + Markdown 下载列表检查
py -m src.report_downloader --ticker 000333.SZ --list-only

# 5. 检查字段覆盖数
# income=86×报告期数, balancesheet=150×报告期数, cashflow=89×报告期数

# 6. 抽查单位：revenue为百万元, total_mv为百万元, total_share为百万股, roe为小数
```

## 项目边界（不做什么）

- 不拉港股、美股、ETF、指数、可转债
- 不做预测数据
- 不做行情 K 线（仅 `daily_basic` 最新市值/股本/价格）
- 不做可视化，只负责取数、标准化、校验和入库
- clean.py 不适用于金融企业（银行/保险/证券），comp_type≠1 的数据会被过滤
- clean.py 已处理年度和季度宽表；季度 BS 明细不完整、CF 5.5 现金桥接残差只允许用显式 QA plug + warning，不做静默补数

## 开发流程

- **架构变更 vs 变更日志，分两个文档维护**（2026-06-22 从原 ARCHITECTURE 第 11 节分离）：
  - **`docs/ARCHITECTURE.md` 写"当前状态"**：新增/修改的模块、数据模型、校验规则、设计决策（第 10 节）、已验证公司口径教训（第 9 节）。改架构时直接改对应章节。第 11 节已改为指向 CHANGELOG 的指针，不再在此维护条目。
  - **`docs/CHANGELOG.md` 写"发生了什么"**：按日期倒序的里程碑变更条目。每次开发完成后在表首追加一行（日期 + 里程碑摘要），**不修改既有历史条目**。完整逐条仍以 `git log` 为准，本表只留里程碑级。
  - 判断口径：描述"系统现在长什么样"→ ARCHITECTURE；记录"这次改了什么"→ CHANGELOG。两者都要，不二选一。
- **凡是修改数据流水线，必须同步更新 `docs/数据流水线.md`**：包括 `data_fetcher.py`、`clean.py`、`financial_expense_analyzer.py` / `financial_expense.yaml`、`defaults_gen.py`、`yaml1_cleaner.py`、`calc.py`、`forecast.py`、`workbench.py` 中任何影响取数、clean、YAML 合并、DCF、历史预测拼接或输出目录契约的变化。

## 运行注意

- Python 路径：确认 `which python` 不指向 WindowsApps，若指向则 `source ~/.bashrc` 或使用完整路径 `/c/Users/Sheld/AppData/Local/Programs/Python/Python311/python.exe`
- `.env` 中 `TUSHARE_TOKEN` 为敏感信息，不可提交至版本控制
- 输出目录 `companies/` 为运行时生成，不纳入版本控制

## Windows + 中文环境约定（踩坑固化）

### 编码：永远别让中文走 stdout

Git Bash 终端默认非 UTF-8，Python `print()` 中文会乱码（`����ҵ`）。内存里的数据是对的，只有终端显示被污染。所以：

- **默认协议：数据落盘再用 Read 工具看，不要 print 调试。** 中间产物一律 `to_csv(encoding='utf-8-sig')` 或 `json.dump(..., ensure_ascii=False)`。
- 确需直接 print 时，脚本顶部加：

```python
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
```

  或运行前 `export PYTHONIOENCODING=utf-8`（有效）。
- `chcp 65001` 在 Git Bash 里无效（那是 cmd 命令），别用。

### 路径：中文读、英文写

中文路径 + 反斜杠 + heredoc 多层转义会打坏路径（`\active` → `ctive`，导致 OSError）。所以：

- 读取走中文原路径，但**字符串一律用 raw**：`r"D:\MKA\companies\新乳业_002946\..."`。
- **中间产物全部写英文临时目录**（如 `C:\temp\xlsm_csv\`），不要往中文目录里写。

### Excel/xlsm 解析标准流程

读券商模型时按此走，避免重复踩坑：

1. raw 字符串读中文路径
2. 逐 sheet `to_csv` 到英文临时目录，UTF-8-sig
3. 用 Read 工具读 CSV（分段读，大 sheet 别全量）
4. 落盘产物可审计，天然适配五层确认协议

### pip

安装包统一加 `-i https://pypi.tuna.tsinghua.edu.cn/simple`
