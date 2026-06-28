---
name: webka
description: 一键打包网页端执行 /ka 所需的规则与材料。本地先跑 ka_prepare markdown 化最高权重材料，强制 /ka §2/§6b 门禁，再把核心纪律 A、核心假设源语言 B、knobs 块契约、核心假设编辑器 runbook 与最高权重材料/BRKD/LOAD/reference/旧稿/defaults.yaml 合并成 `必读和素材.md`，core_metrics_overview + OfficialBreakdowns 合并成 `不必要读强制碰到再速查.md`，加一份 `readme first.md` 入口，输出到 WEBCLAUDE/webka(Claude帮你统摄核心假设）/。纯打包，稿子回收手动走本地 /ka。
argument-hint: [公司名或代码，如 新乳业 / 002946] [--rebuild]
allowed-tools: Read, Grep, Glob, Edit, Write, Bash
---

# /webka - 网页端 /ka 打包器

`/webka` 是网页端执行 `/ka` 的准备器。真正的裁决仍由网页端 `/ka` 完成；`/webka` 只负责本地预 staging：跑 `ka_prepare` 把最高权重材料 markdown 化（网页端读不了 raw PDF/Word），强制 /ka 门禁，然后把网页端需要的规则与材料预合并成 3 份 Markdown。网页端上传这 3 份即可。

## 范围

- `/webka` 是纯打包器，**不在本地做裁决、不落盘核心假设**。
- 网页端产出的 `核心假设.md` 由用户拷回本地，按 /ka 铁律 1 走 `ka_archive` + 写今日新稿 + `/comp`（见 `readme first.md`）。
- 不写 manifest：无下游机器消费打包结果，报告 print 到终端。

## 执行动作

1. 解析公司目录，接受公司名、裸代码、完整 ticker 或公司目录。
2. 运行：

```bash
py -m src.webka "{公司}" [--rebuild]
```

3. `src.webka` 会先跑 `src.ka_prepare`，把 `公司判断和最新观点.md` + `Skills素材包/最高权重材料-放Agent最应对齐的材料/` 顶层材料 markdown 化到该目录 `markdown存储区/`。
4. 强制两道门禁（与 /ka 一致，硬停）：
   - **§2 已有正式稿门禁**：根目录有正式 `*核心假设*.md` 且未加 `--rebuild` → 停，分流到 `/adj`、`/frontend-edit`、`/annual-update`。`--rebuild` 放行，旧稿作对照并入 `必读和素材.md`。
   - **§6b 骨架门禁**：BRKD（`Agent业务讨论.md`）/ 已完成 LOAD（KA 参考稿区 `核心假设参考load_*.md`，须有 ` ```knobs` 块且非「待模型装载器补全」脚手架）/ KA 参考稿区 reference 候选（`核心假设参考*.md`，剔除 load）三者全无 → 停。
5. 清空并重建：

```text
companies\{公司}\WEBCLAUDE\webka(Claude帮你统摄核心假设）\
```

## 打包清单

网页端包只含 3 份 Markdown：

- `readme first.md`：入口（任务/读取顺序/门禁预检结果/输出契约/不能跑脚本/带回本地步骤）。
- `必读和素材.md`：合并以下来源，按读取顺序排列——
  - `核心纪律_skill_v*.md`（A）
  - `核心假设源语言_skill_v*.md`（B）
  - `docs/knobs块契约.md`
  - `核心假设编辑器_skill_v*.md`（裁决 runbook §1-§10）
  - `公司判断和最新观点.md` + 最高权重材料 `markdown存储区/*.md`
  - `Agent/defaults.yaml`（§1.1 审计对象）
  - BRKD `Agent业务讨论.md`、最新 LOAD 产物、reference 候选（有则并入）
  - 旧正式稿（仅 `--rebuild`，作对照）
- `不必要读强制碰到再速查.md`：合并 `Agent/core_metrics_overview.md` + `Agent/OfficialBreakdowns/*.csv`。

明确不打包：

- `core_metrics_overview.json/.csv`：与 `.md` 同源，`.md` 可读性最佳，只取 `.md`。
- `financial_expense.yaml`：/ka 默认不裁决财费，且常处 LLM 未跑的低质态；如需附注构成，本地补跑 `financial_expense_analyzer` 后手动贴。
- 年报正文 Markdown：太大，/ka §7 年报是按需查证不是主材料；如需附注 excerpt，用户手动贴。
- `Agent/data.db`：web 无法查 SQLite；derived 事实已由 `core_metrics_overview` 与 `OfficialBreakdowns` 覆盖。
- `docs/yaml1算法模板契约.md`：/comp 读，/ka 不加载。
- 任何 manifest json：纯打包，无下游消费。

## 网页端怎么跑

把输出目录下 3 份 md 上传到网页端后，先让网页端读 `readme first.md`。

网页端必须遵守：

- 这是 `/ka`，不是 `/load`；是全量生成/重建，不是 modify。
- 不能跑脚本、不能读写本地文件系统；规则与材料全在 `必读和素材.md`。
- 读取顺序：`readme first.md` → `必读和素材.md` 全读 → `不必要读强制碰到再速查.md` 碰到才查。
- 裁决流程进 `必读和素材.md` 里的编辑器 runbook §1-§10，押→拍板→落盘，七段停。
- 范围边界、分红率强制检测、family 硬规则、knobs 语法等细节见 `必读和素材.md` 对应规则节，不在聊天复述。
- 输出一份 `{公司名}-YYYYMMDD-核心假设.md`：抬头（`模式: ka` / `状态: official` 或 `reference` / 历史数据至 / 显式预测期 / 衰减期至 / 衰减交接增速 / 永续增长 / 门槛来源）+ 业务线块 + 末尾 ` ```knobs` 机器自报清单。

## 带回本地

网页端产出稿子后，用户拷回公司根目录，按 /ka 铁律 1 落盘：

```bash
py scripts/ka_archive.py "<旧正式稿完整路径>"   # 重建时先归档旧稿
# 再 Write 成 companies\{公司}\{公司名}-{今日YYYYMMDD}-核心假设.md
py -m src.forecast --ticker {代码}.SZ           # 再跑 /comp + DCF
```

## CLI

```bash
py -m src.webka 新乳业
py -m src.webka 002946
py -m src.webka 002946.SZ --rebuild
```

## 退出码

- `0`：成功，3 份 md 已写入 `WEBCLAUDE/webka(...)/`。
- `2`：公司解析失败、`ka_prepare` 失败，或缺少必备规则文件。
- `3`：§2 已有正式稿门禁或 §6b 骨架门禁未过。
- `1`：其他 IO 异常。
