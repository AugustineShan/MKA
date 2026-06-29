# MKA - A股财务数据拉取与校验系统

STOP：先判斜杠路由，再选择任何外部技能。`/ka 百润股份`、`/ka 002568`、`/comp 002946`、`/init 新乳业` 这类命令一律先解释为 MKA 任务路由；即使公司名或股票代码像证券问题，也不是行情查询、不是交易建议、不是通用 A 股分析、不是 shell。只有用户明确说“查行情/股价/涨停/分时/盘面/资金”时，才可以调用股票行情分析能力。

两阶段流水线：① TuShare Pro 拉三表 → 标准化 → 入库 SQLite；② 从 SQLite 读原始 → 透视宽表 → 严格配平校验 → 写 clean 表。建模管线在取数之上：/brkd → /ka → /comp → DCF。

规则边界或例外分流不清楚时，先读 `docs/MKA规则导航图.md`。它是契约索引，不替代具体 skill 或契约。

人工筛选是第一门禁：markdown 存储区和 cache 默认不是证据入口；只有人工放入同权重判断材料、BRKD/LOAD/Alphapai 完成产物、KA 目录顶层 markdown 或 `/init` 事实索引的内容，才进入本轮裁决。

入口窄，收纳宽：已进入本轮的材料里，有复盘价值但暂不入模的信息宁可进收纳区/stash，不得因为减负乱扔。

斜杠词是 MKA 路由：`/ka 百润股份`、`/comp 002568`、`/init 新乳业` 这类命令不是行情查询、不是交易建议、不是 shell。只有用户明确说“查行情/股价/涨停/分时/盘面/资金”时，才离开 MKA 路由。

---

## 🔴 三条铁律（优先于一切）

**1. 核心假设.md 永不原地覆盖。** 任何对 `核心假设.md` 的编辑（/ka 的 init/modify、/frontend-edit）都必须两步、顺序不可反：

1. 先归档旧稿：`py scripts/ka_archive.py "<旧稿完整路径>"`，移到 `companies\{公司}\Agent\KAhistory\`（tracked 用 `git mv` 保历史，撞名加 `-HHMMSS`，只移动不改内容）。
2. 再写今日新稿：Write 到 `companies\{公司}\{公司名}-{今日YYYYMMDD}-核心假设.md`（参考稿则 `…核心假设参考.md`）。**文件名日期必须是今日**，不沿用旧稿日期。根目录只剩今日一份，旧稿全在 KAhistory。

禁止：① 直接 Edit 旧稿；② Write 覆盖旧稿路径；③ 新稿沿用旧日期。同日重跑也照两步（先归档撞名加后缀，再写今日同名）。

**2. 通用性高于一切。** 本系统为兼容千奇百怪的公司而建，绝不把任何一家的形状焊进代码/模板/契约/校验器。

- 不写死任何公司特征：行名、业务线数量、公式族、科目、单位、拆分层级都随公司变。
- 驱动来自声明，不来自样本：模板/契约/校验由"公司声明了什么结构"驱动（family/anchor/unit/path 都是声明式），不由样本公司的固定形状驱动。
- **看到自己在为某家公司特判，就停**——退一步一般化。样本只用来验"形"，不定义结构。
- 长尾优先于顺手：宁可多想一种没见过的形态（门店×单店、用户×ARPU、保费×综合成本率、产能滞后链…），不为当前这家收窄通用性。

**3. TuShare 数据缺口 = 用 reconciler 去年报里拉干净（本项目存在的根本理由）。** 当 `clean.py` 年度硬校验出现 `target_gt_calc`（合计 > 明细和，即 TuShare 漏披露明细）时，默认动作就是 `annual_report_reconciler.py` 去年报 Markdown 补回缺失金额、LLM 高置信确认后生成 approved override、重跑 clean 应用——**不要问"要不要保持失败/要不要人工"**。

- `raw_tushare` 永不被修改；补全只进年度 clean 宽表 + 写 `clean_adjustments`/`clean_warnings` 审计。
- 唯一例外：`target_lt_calc`（明细和 > 合计，clean.py 自己重复计数/误分类）是 clean.py 的 bug，应修字段分类，不走 reconciler。**但 IS 1.2 营业利润例外**——常因 TuShare 缺失负值 `asset_disp_income`（资产处置收益）致 calc 偏大，仍属 TuShare 缺口走 reconciler（见校验层级 IS 1.2 规则）。

---

## 🧭 路由（改这些去哪）

- **首次上手 / 冷启动** → 先读 `docs/快速上手.md`（端到端主线：`/init → /brkd → /ka → /comp → forecast`），再按需查 `docs/技能简要分类.md` 分流。
- **调用/修改 skill** → 先读 `docs/技能简要分类.md` 分流；任何新增或修改 skill，必须同步更新该文档，并保留 `CLAUDE.md` / `Codex.md` 的入口提示。
- **改核心假设生成类技能** → `/brkd`、`/load`、`docs/Alphapai/Alphapai业务拆分抓取器.md`、`docs/Alphapai/Alphapai-load核心假设参考提示词.md`、`/ka` 同属核心假设生成链路。改其中一个的骨架、门禁、业务拆分历史要求、会议 memo 方式、`knobs`/reference 边界时，必须检查另外几个是否需要同步；同步的是共同骨架和接口纪律，不是互相复制职责。
- **改字段分类/排序/标签** → 只编辑 `src/field_registry.yaml`（三表 325 字段唯一真源），别再找 clean.py 的分类字典或 workbench 排序声明，它们已不存在、都从 registry import。详见 `docs/会计系统.md`。
- **改前端** → `docs/前端设计规范.md` 为权威，改前端前必读；实际色值以 `app/src/styles.css` 的 CSS 变量为准（`--blue:#003d7a`、`--red:#b42318`）。
- **改架构 / 记变更** → 当前状态写 `docs/ARCHITECTURE.md`，发生了什么写 `docs/CHANGELOG.md`（见开发流程）。
- **已知 TuShare 缺陷线索** → `knowledge/known_tushare_defects.json`（reconciler 的 LLM 检索提示，不是补丁库）。

## 技术栈

- **语言**：Python 3.11+（系统全局，禁止 venv）
- **依赖**：`tushare>=1.4.0`, `pandas>=2.0.0`, `requests>=2.31`, `pymupdf>=1.24`
- **存储**：SQLite，每公司一个 `companies/{公司名}_{代码}/Agent/data.db`
- **数据源**：TuShare Pro（经中转站 `fastapic.stockai888.top` 代理）；巨潮 cninfo 用于年报 PDF + Markdown

## 项目结构

```
MKA/
├── src/
│   ├── init.py                  # 一键编排入口（stage 拉取→clean→年报→reconcile→plug）
│   ├── data_fetcher.py          # 阶段①：TuShare拉取+标准化+入库
│   ├── clean.py                 # 阶段②：EAV→宽表+配平校验+写clean表
│   ├── core_metrics_overview.py # clean_annual → 年度核心指标事实速览
│   ├── field_registry.py / .yaml# 三表字段元数据唯一真源（分类/会计序/标签/resolve/sign）
│   ├── report_downloader.py     # cninfo 年报 PDF + Markdown 批量下载
│   ├── annual_report_utils.py   # 年报 MD/LLM 公共工具（reconciler/analyzer 共用）
│   ├── annual_report_reconciler.py  # 年度硬校验失败后的年报智能核对/补全
│   ├── annual_report_extractor.py   # 年报 Markdown LLM 萃取
│   ├── financial_expense_analyzer.py# 财务费用附注 → financial_expense.yaml
│   ├── defaults_gen.py          # clean_annual/meta → defaults.yaml（唯一YAML2）
│   ├── yaml1_cleaner.py         # yaml1 + defaults.yaml → 内部 forecast params
│   ├── forecast.py              # 正式DCF入口：defaults + yaml1 → Agent/forecast/
│   ├── calc.py                  # 纯算账核/回归（只吃清洗后参数表，永不见yaml1）
│   ├── yaml2_schema.py          # YAML2 读写与校验
│   └── workbench.py             # FastAPI 本地壳，读 companies/ 调 src.forecast
├── docs/                        # ARCHITECTURE / CHANGELOG / 会计系统 / 前端设计规范 / 数据流水线
├── companies/{公司名}_{代码}/    # 输出目录（运行时生成，不纳入版本控制）
│   ├── 公司判断和最新观点.md
│   ├── Agent业务讨论.md          # /brkd 产出：业务预理解参考
│   ├── *核心假设*.md
│   ├── Skills素材包/             # 活跃收集，不移动；以下子目录被 skill 路由消费：
│   │   ├── LOAD外部EXCEL模型理解器（一次最多一个）/   # /load、/ka 读外部 Excel 模型
│   │   ├── BRKD业务理解器（研报和纪要放在这里）/     # /brkd 读研报/纪要
│   │   ├── 最高权重材料-放Agent最应对齐的材料/       # /ka 读取（ka_prepare 幂等 markdown 化）
│   │   ├── ADJ增量信息（用来改模型的边际信息）/       # /adj incremental 读取（adj_prepare 幂等 markdown 化）
│   │   ├── KA（ALPHAPAI拆出来的东西放在这里）/        # /ka 人工入口：顶层 *.md 全读；核心假设参考* 按候选稿，其余按信息指引
│   │   └── PJBG评级报告素材区/                      # 占位，暂无消费方
│   ├── 公告/{年报,季报,临时公告}/  研报/ 纪要/ 收集/ 重要文件/ 内部报告/  # 常规材料目录
│   ├── WEBCLAUDE/               # 高频打包区，供网页 Claude 上传
│   └── Agent/                   # 建模运行区（核心契约层）：
│       ├── data.db             # raw_tushare/meta/clean_annual/clean_quarterly/clean_adjustments/clean_warnings
│       ├── core_metrics_overview.md/json/csv
│       ├── defaults.yaml       # 唯一 YAML2：机器平推底座
│       ├── financial_expense.yaml
│       ├── yaml1*.yaml         # compiler 输出：人的判断覆盖层
│       ├── recon/              # 年报核对 evidence JSON
│       ├── .modelking/         # 内部编译产物，非人工维护界面
│       └── forecast/           # 唯一正式 DCF 输出（每次重算先清空再生成）
├── vendor/use_cninfo/           # vendored rollysys/use_cninfo（MIT）
└── .refs/tushare-docs/          # 33.md(income) 36.md(balancesheet) 44.md(cashflow) 等官方文档缓存
```

## 数据流水线

```
TuShare API
  ↓ data_fetcher.py（阶段①）
data.db: raw_tushare(EAV) / meta(KV)
  ↓ clean.py（阶段②；宽表行=period，列=325官方字段+6 QA plug，严格配平保 warning）
data.db: clean_annual / clean_quarterly
  ↓ core_metrics_overview.py（只读 clean_annual，年度利润表主链路，不含预测）
Agent/core_metrics_overview.md/json/csv
  ↓ financial_expense_analyzer.py（可选；年报财务费用附注按年份归档）
Agent/financial_expense.yaml
  ↓ defaults_gen.py
Agent/defaults.yaml（唯一YAML2：完整、配平、无判断的机器平推底座）
  ↓ forecast.py：yaml1*.yaml + defaults.yaml
Agent/forecast/（唯一正式 DCF；中间参数写 Agent/.modelking/）
```

## 建模三站管线（/brkd → /ka → /comp）

```text
研报/纪要 → /brkd → Agent业务讨论.md → /ka → 核心假设.md → /comp → yaml1
            读懂(discernment)   记全(fidelity)      译准(翻译)
```

- `/brkd`：读 `Skills素材包/BRKD…/` 的研报纪要，产出 `Agent业务讨论.md`（公司根目录），作 /ka 业务预理解参考。
- `/ka`：消费 `Agent业务讨论.md` + `Skills素材包/LOAD…/` 外部模型，产出 `*核心假设*.md`。
- `/comp`：把 `核心假设.md` 编译为 `yaml1*.yaml`。

核心假设生成类技能同步纪律：

- 同链路技能：`/brkd`、`/load`、`docs/Alphapai/Alphapai业务拆分抓取器.md`、`docs/Alphapai/Alphapai-load核心假设参考提示词.md`、`/ka`。
- 必须保持相似骨架：时间边界/材料边界、业务拆分历史、收入→毛利→费用→below-OP→terminal 的段序、会议 memo、reference/draft/official 状态、`knobs` 同源边界。
- 必须保持分工隔离：`/brkd` 挖研报/纪要和 `/init` 事实，产出 draft；`/load` 只保真装载旧 Excel 的 load-vintage，不用后验材料补数；Alphapai业务拆分抓取器只抓用户指定主拆分、桥表和高价值辅助拆分历史 factpack，不写预测；Alphapai-load 用网页端数据库产 reference 并承接 factpack；`/ka` 只裁决候选并生成 official，不读原始 Excel/研报。骨架要同步，职责不能互相污染。

## DCF 运行规则

用户只维护两类输入：`defaults.yaml`（YAML2，机器平推底座）和 `yaml1*.yaml`（人的判断覆盖层）。正式命令：

```bash
py -m src.forecast --ticker 002946.SZ
```

内部执行 yaml1_cleaner 的 fold/expand/resolve/backtest，再把标准参数交给 calc.py。默认只在 `Agent/forecast/` 暴露最终结果。

- **`Agent/forecast/` 是唯一正式输出目录，每次重算先清空再生成**；禁止用 `forecast_current/forecast_fixed/forecast_yaml1` 这类目录承载正式结果。
- 中间产物（forecast_params.yaml / yaml1_clean_report.json）只写 `Agent/.modelking/`，**不要在公司目录顶层生成或维护**。
- `defaults.yaml` 是唯一 YAML2；清洗后的逐年标准参数表不是 YAML2，不要在顶层维护 `yaml2_yearly.yaml`。
- **calc.py 永远看不到 yaml1，也不直接读 defaults.yaml**——只接受 `--forecast-params`（清洗后参数表）。defaults 进 calc 的唯一合法路径是先过 yaml1_cleaner（无 yaml1 时 `--defaults-only` 做恒等清洗）。有 yaml1 的公司走 `py -m src.forecast`。
- **capex 双重扣减陷阱**：`balance_sheet.capex_pct` 必须是合并口径（`c_pay_acq_const_fiolta / revenue`，defaults_gen 默认产出）。calc.py 据此把 PP&E 份（`capex − Σ三项摊销`）灌进 `fix_assets`；若 yaml1 把 `capex_pct` 改成固定资产口径会双重扣减，且无自动守卫。

## 本地 Web 工作台（FastAPI + React）

把 `companies/{公司名}_{代码}/` 映射为一家公司一页，第一版只读展示 + 一键重算。**工作台不是新建模入口，重算按钮必须调 `src.forecast`**，仍遵守 `defaults.yaml + yaml1*.yaml → Agent/forecast/`。

```bash
npm install && npm run build     # 验证 React/Vite 前端
py -m src.workbench              # 启动 FastAPI，打开 http://127.0.0.1:8765
```

Windows 双击入口 `入口.cmd`（首次自动装依赖、之后每次双击直接启动）；开发前端可 `npm run dev`，日常预览走 `py -m src.workbench`（重启前先杀 8765 僵尸进程）。风格 Apple HIG / SF Pro，**完整规范见 `docs/前端设计规范.md`（权威，改前端前必读）**，本节只是入口速记。

---

## 校验层级

- **硬校验**（CheckError 报错停止）：IS 1.1-1.6、BS 2.1-4.3、CF 5.1-5.5、IS补充 6.1-6.3、跨表 7.1、逐年连续性 7.4。季度 BS bucket 小计残差和 CF 5.5 现金桥接残差先进显式 QA plug + warning，plug 后仍不平才停。
- **软校验**（仅 warning）：跨表 7.2-7.3、方向合理性 10.1、量级 10.2、折旧vs固定资产 10.3、毛利率范围 10.4。
- **容差**：残差 < 1（百万元）。
- **年度失败处理**：annual hard check 失败默认强触发 reconciler（只生成 evidence/override，不修改 raw，不静默放行）。
- **IS 1.2 optional 调整项 + NULL provenance**：`oth_income`/`credit_impa_loss`/`asset_disp_income` 等 optional 调整项，TuShare 对部分公司全年返回 NULL，`fillna(0)` 会把 NULL 抹成 0 致缺口被静默吞掉。规则：`pivot_to_wide` 在 fillna 前捕获 income 端 NULL 字段集（存 `wide.attrs["null_fields_by_period"]`），传给 `check_is`/`check_soft`；`missing_optional_is_adjustments` **只放行"raw 非 NULL 且值≈0"的字段、排除 NULL**；残差>0 且存在 NULL optional 时 IS 1.2 **硬失败**进 reconciler 闭环。reconciler `collect_failures` 同步从 `wide.attrs` 取 null_fields，保证看到与 clean 一致的失败。

## 合并科目 resolve 规则

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
| `raw_tushare` | (ticker, endpoint, report_type, end_date, field) | TuShare 原始镜像，完整保留官方字段，**永不修改** |
| `meta` | key | 公司元信息（ticker, name, total_share, total_mv 等） |
| `clean_annual` | period | 年度 clean 宽表：325 官方字段 + 6 QA plug |
| `clean_quarterly` | period | 季度 clean 宽表：325 官方字段 + 6 QA plug |
| `clean_adjustments` | — | clean 阶段应用的 approved 年报补数审计，不改 raw |
| `clean_warnings` | — | clean 阶段 warning（补数 + 软校验） |

---

## 关键约定（改代码必守）

### 字段命名
- **只用 TuShare 官方字段名**（如 `n_income_attr_p`、`total_hldr_eqy_inc_min_int`、`c_pay_acq_const_fiolta`）；唯一例外是 clean 阶段 6 个 `qa_*_plug` 审计字段。
- 禁止任何内部别名；`field_terms.csv`、`statement_field_coverage.csv` 不得出现非官方字段。

### field_registry 是会计科目与排序的唯一真源
三表 325 字段元数据（哪张表/哪个 bucket/会计序/中文标签/是否小计/resolve 父子/符号语义）全声明在 `src/field_registry.yaml` 一处。clean.py 的分类/resolve/sign 字典与 workbench 的渲染排序/标签都 `from .field_registry import`，`docs/数据格式参考.md` 由 `scripts/gen_field_reference.py` 派生。

- **flat 有序列表 = 会计序**：`statements.<income/balancesheet/cashflow>.fields` 列表顺序即准则序=前端展示序。`category_order`（展示桶序，不含 subtotal）+ `category_labels`（全 category→中文）分离声明。小计字段（category=subtotal）的列表位置即展示位置。
- label 直接带"减:/其中:"前缀；三个 BS 总计标 `role: total`。
- **改字段分类/排序只编辑 `field_registry.yaml`**，`tests/test_field_registry.py` 守内部一致性（字段数/标签覆盖/resolve 引用/combo 同桶/total_fields）。
- `check_is/bs/cf` 的 subtotal 公式仍写在代码里（元数据同源，公式不数据驱动）；`known_tushare_defects.json` 独立保留。

### 单位转换（入库单位）
| 类别 | 入库单位 | 转换 |
|------|----------|------|
| `amount_cny` | 百万元 | 元 ÷ 1,000,000 |
| `percent` | 小数 | 原值 ÷ 100 |
| `share` | 百万股 | 股 ÷ 1,000,000 |
| `daily_basic_share_10k` | 百万股 | 万股 ÷ 100 |
| `daily_basic_mv_10k_cny` | 百万元 | 万元 ÷ 100 |
| `turnover_rate` | 天 | 365 ÷ 周转率 |
| `ratio` / `price` | 原值 | 不转换 |

**`total_share` 口径特例**：TuShare balancesheet `total_share` 是股数（百万股）不是股本（元），且无独立股本字段。`infer_par_value` 按权益恒等式跨年推断面值（离散法定常量 1/0.1/0.5/…，平票归 1.0），`check_bs` BS 4.1 按 `股本(元)=par×total_share` 折算参与求和——**仅校验折算，存储值不变**（下游每股计算仍用股数）。属 clean.py 内字段口径修复，不走 reconciler。

### 去重规则（同一 end_date 多条）
1. `report_type='1'`（合并报表）
2. `comp_type='1'`（一般工商业，非此跳过并 warning）
3. 优先 `update_flag='1'`
4. 再取 `f_ann_date` 最晚 → `ann_date` 最晚

### 入库健康检查（硬校验，不过拒绝入库）
三表各有记录；主键无重复；ticker 一致；每端点每报告期覆盖官方全部数值字段；最新年度核心字段不缺（revenue, n_income_attr_p, total_assets, total_liab, total_hldr_eqy_inc_min_int, n_cashflow_act 等）；meta 含 ticker/name/latest_trade_date/total_share/total_mv；BS 配平 total_assets≈total_liab+total_hldr_eqy_inc_min_int（容差 0.01）；现金流勾稽 CFO+CFI+CFF+汇兑≈现金净增（0.01）；季度加总 Q1+Q2+Q3+Q4=年报（0.01）。

### 限速与重试
- 每次请求后等 0.8s（约 75次/分，低于中转站 100次/分）；限频错误等 60s 重试，最多 3 次；鉴权/权限错误直接抛出不重试。

### 官方文档字段数量（校验基准）
| endpoint | 数值字段数 | 本地文档 |
|----------|-----------|----------|
| `income` | 86 | `.refs/tushare-docs/33.md` |
| `balancesheet` | 150 | `.refs/tushare-docs/36.md` |
| `cashflow` | 89 | `.refs/tushare-docs/44.md` |

---

## 模块公共 API

```python
# data_fetcher.py
fetch_company("600519.SH", force_refresh=False) -> str   # 返回 SQLite 路径
fetch_companies(["600519.SH", "300866.SZ"]) -> dict

# clean.py
clean(r"D:\MKA\companies\某公司_002946\Agent\data.db", "002946.SZ") -> pd.DataFrame
```

（关键类/函数清单见各模块源码与 `docs/ARCHITECTURE.md`，不在此维护以免与代码漂移。）

## 年报智能核对 annual_report_reconciler.py

clean.py 的外置补全/诊断，只在年度硬校验失败且本地已有年报 Markdown 时使用。复用 clean.py 的年度透视/字段分类/combo resolve/`apply_annual_income_subtotal_adaptations`/`check_*` 收集失败（**collect_failures 前先跑 adaptation 并应用已有 approved override**，保证 reconciler 看到的失败 = clean.py 实际失败）。**永不修改 data.db / raw_tushare / clean_***。

- **LLM**：GLM `glm-5.2`（推理模型；`call_llm` 对含 "5.2" 的 model 自动发 `thinking:{"type":"disabled"}`，否则烧 reasoning_tokens 致 max_tokens 截断返空，`GLM_THINKING=enabled` 可覆写）。429 用 30/60/90s 长退避（GLM 按分钟限流，短退避会把整片静默吞成假阴性）。
- **两层补全**：① rule-first（别名+金额正则 + Phase B LLM 确认，精确便宜）；② 残余进 `_llm_propose_fallback`（`full_context=True` 让 NCA/权益尾部可见）。
- **三层防脏 override 守卫**：① `failure_candidate_fields` 所有分支**排除 `subtotal`**（subtotal 是校验目标不是待补明细，纳入即允许改写校验目标=脏配平）；② collect_failures 前先跑 income subtotal adaptation（IS 1.1 小残差本就被兜底，不误报为 failure）；③ `add_override` **拒绝非 0 `old_value`**（只补漏录/为 0 字段，不覆盖已有非 0 值）。
- **应用范围**：clean.py 只应用 `status=approved` 且 `source∈{glm（当前）, kimi（历史兼容）}` 的记录，**且只应用到年度 clean 宽表**；每条写 `clean_adjustments`，warning 写 `clean_warnings`。
- **CLI**：`--no-llm`、`--write-overrides`（与 `--no-llm` 互斥）、`--approve-high-confidence`、`--no-auto-reconcile`、`--auto-reconcile-max-failures N`。默认 override 文件合并旧记录，不覆盖已有 approved 证据。

### 两道年份闸门
- **2010 闸门**：强触发与核对只对 ≥2010 年生效；2010 前硬失败**降级为 warning 直接入库**（不阻塞、不触发 reconciler）。`RECONCILE_MIN_YEAR=2010` 是唯一闸门常量。原因：A 股 2010 前披露稀疏。
- **pre-IPO 闸门**：上市前年份的 TuShare 数据来自招股书，cninfo 无该年年报 MD，reconciler 无可核对。`clean.earliest_annual_md_year(db)` 取最小年报 MD 年份为边界，早于该年的硬失败降级为 warning 入库、reconciler 跳过。`init.py stage_clean` 在年报下载完成后重跑一次 clean（此时 MD 已可用、闸门生效），由此通过则直接成功不再触发 reconciler。无年报 MD 时返回 None、闸门关闭、退回原行为。

### 两轮补数 + 年度 plug 兜底（init.py 编排，`MAX_BACKFILL_CYCLES=2`）
1. 第一轮：clean 失败 → 强触发 reconciler 提议 override。
2. 第二轮：reconciler 在 collect_failures 前先应用第一轮 approved override，专攻更小残差。
3. 两轮都不过 → `_offer_annual_plug` 交互问用户是否塞年度 QA plug。同意 → 写 `Agent/recon/annual_plugs.json`（`period` 为纯年份）→ 重跑 `clean.py --mode annual --allow-annual-plug`。

`clean.py` 年度 plug：`apply_annual_bs_plugs` **只在用户指令的 (period, code) 生效**（非自动全期），check_bs 经 `qa_bs_*_plug` 自动吸收残差，写 `annual_bs_plug` warning。**年度 plug 是诚实逃生通道不是常规兜底——关键科目建议拒绝 plug、如实留 exit 3。**

## 季度 QA plug 收纳科目

季度披露弱于年报，clean.py 在 quarterly 模式允许用显式 QA plug 吸收 BS bucket 小计残差：`qa_bs_current_asset_plug`、`qa_bs_noncurrent_asset_plug`、`qa_bs_current_liab_plug`、`qa_bs_noncurrent_liab_plug`、`qa_bs_equity_plug`、`qa_cf_cash_reconcile_plug`。

非官方字段，仅 clean 审计字段。年度/季度 clean 表都保 325 官方 + 6 QA plug 保 schema 统一，年度 plug 正常为 0。季度 BS plug 只参与 BS 2.1/2.2/3.1/3.2/4.1 bucket 小计校验；`qa_cf_cash_reconcile_plug` 只参与 CF 5.5 现金桥接，不参与 CF 5.1-5.4 流量明细。用 plug 必须透明：`clean_warnings` 写清哪里合不上、目标值、计算值、残差、用哪个 plug 字段、建议检查对应季报。

## known_tushare_defects.json 与 override 重分类

`knowledge/known_tushare_defects.json` 是给 reconciler 的轻量 LLM 检索提示（索引用"触发条件 + 字段"，**不用公司名**；命中只把 hint 写入 reconciliation JSON 并加入检索词，**不作自动补数依据**，仍须年报片段金额 + LLM high confidence 确认）。最常见的两类系统性漏录（详情查 JSON）：

- **NCA/NCL 新准则科目**（`BS 2.2`/`BS 3.2` target_gt_calc）：`oth_eq_invest`、`oth_illiq_fin_assets`、`use_right_assets`、`lease_liab` 等，TuShare 按公司全年留空但年报披露了；单字段闭合不了时考虑 2-3 项之和。
- **IS operating_adjustment 系统性 NULL**（`IS 1.2`）：`oth_income`/`credit_impa_loss`/`asset_disp_income` 等，常需多字段联合闭合，reconciler `llm_override_suggestions` 已支持。

**override clean_category 重分类**：部分 TuShare 字段的 bucket 归属对个别公司不成立（典型 `estimated_liab` 预计负债，TuShare 默认非流动但比亚迪列报为流动）。**不能改 clean.py 静态分类**（会破坏其他公司），而由 reconciler 在 override 写 `clean_category`，clean.py 应用时只对该公司该期重分类到目标 bucket（写 `wide.attrs["bs_reclass"]`，`bs_bucket_sum` 按 reclass 取 bucket）。字段值照常补进宽表，bucket 加总落到正确一侧，`clean_adjustments` 记审计。

## 年报 PDF + Markdown 下载 report_downloader.py

复用 `vendor/use_cninfo/src/cninfo` 封装，项目根只维护薄脚本。输出 `companies/{公司名}_{代码}/公告/年报/`，文件名 `{年份}_年度报告.pdf`（修订版 `_修订版`），Markdown 同名（YAML frontmatter + PyMuPDF 全文）。只保留 `YYYY年年度报告` 与修订版，排除摘要/英文版；按年份新→旧、同年修订版优先；已存在分别跳过；cninfo 请求/下载间隔 1-2 秒。CLI 见验收方式。

---

## 验收方式

```bash
# 1. 语法检查
py -m py_compile src/data_fetcher.py src/clean.py src/report_downloader.py

# 2. 阶段①拉取
py -m src.data_fetcher --ticker 300866.SZ --force --verbose

# 3. 阶段②清洗+配平校验
py -m src.clean --ticker 300866.SZ --verbose
#   --mode annual|quarterly · --no-overrides · --no-auto-reconcile · --allow-annual-plug · --db <path>

# 4. 年报 PDF + Markdown 下载列表
py -m src.report_downloader --ticker 000333.SZ --list-only
#   --force-markdown · --no-markdown

# 5. 年报智能核对
py -m src.annual_report_reconciler --ticker 000333.SZ
#   --only-year 2025 --only-code "BS 2.1" · --no-llm · --write-overrides --approve-high-confidence

# 6. 正式 DCF
py -m src.forecast --ticker 002946.SZ

# 检查：字段覆盖 income=86×期数, balancesheet=150×期数, cashflow=89×期数
# 抽查单位：revenue/total_mv=百万元, total_share=百万股, roe=小数
```

## 项目边界（不做什么）

- 不拉港股/美股/ETF/指数/可转债；不做预测数据（取数侧）；不做行情 K 线（仅 daily_basic 最新市值/股本/价格）；不做可视化（取数库只负责取数/标准化/校验/入库）。
- clean.py 不适用于金融企业（comp_type≠1 会被过滤）；季度 BS 明细不完整、CF 5.5 残差只允许显式 QA plug + warning，不做静默补数。

## 开发流程

- **架构变更 vs 变更日志，分两个文档**：`docs/ARCHITECTURE.md` 写"当前状态"（模块/数据模型/校验规则/设计决策/已验证公司口径教训），改架构直接改对应章节；`docs/CHANGELOG.md` 写"发生了什么"（按日期倒序里程碑，每次开发完表首追加一行，**不改既有历史条目**，逐条以 git log 为准）。两者都要，不二选一。
- **凡改数据流水线必须同步更新 `docs/数据流水线.md`**：data_fetcher / clean / core_metrics_overview / financial_expense_analyzer / defaults_gen / yaml1_cleaner / calc / forecast / workbench 中任何影响取数、clean、事实速览、YAML 合并、DCF、历史预测拼接或输出目录契约的变化。

## 运行注意

- Python 路径：确认 `which python` 不指向 WindowsApps，若指向则 `source ~/.bashrc` 或用完整路径 `/c/Users/Sheld/AppData/Local/Programs/Python/Python311/python.exe`。
- `.env` 的 `TUSHARE_TOKEN` 为敏感信息，不可提交；`companies/` 为运行时生成，不纳入版本控制。

## Windows + 中文环境约定（踩坑固化）

### 编码：永远别让中文走 stdout
Git Bash 默认非 UTF-8，Python `print()` 中文会乱码（内存数据是对的，只有终端显示被污染）。

- **默认协议：数据落盘再用 Read 工具看，不要 print 调试。** 中间产物一律 `to_csv(encoding='utf-8-sig')` 或 `json.dump(..., ensure_ascii=False)`。
- 确需 print：脚本顶部加 `sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')`，或运行前 `export PYTHONIOENCODING=utf-8`。
- `chcp 65001` 在 Git Bash 无效（那是 cmd 命令），别用。

### 路径：中文读、英文写
中文路径 + 反斜杠 + heredoc 多层转义会打坏路径（`\active`→`ctive` 致 OSError）。

- 读取走中文原路径，但**字符串一律 raw**：`r"D:\MKA\companies\新乳业_002946\..."`。
- **中间产物全部写英文临时目录**（如 `C:\temp\xlsm_csv\`），不往中文目录写。

### Excel/xlsm 解析标准流程
1. raw 字符串读中文路径 → 2. 逐 sheet `to_csv` 到英文临时目录（UTF-8-sig）→ 3. 用 Read 工具读 CSV（大 sheet 分段）→ 4. 落盘产物可审计，天然适配五层确认协议。

### pip
统一加 `-i https://pypi.tuna.tsinghua.edu.cn/simple`
