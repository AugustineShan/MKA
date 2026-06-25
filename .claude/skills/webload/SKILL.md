---
name: webload
description: 一键准备 /load 时间沙箱，并把网页端执行 /load 所需的共享纪律、核心假设源语言、load 运行纪律、边界、禁读清单、模型装载器和 `{原Excel文件名}_核心假设_load{YYYYMMDD}.md` 脚手架预合并成一个 Markdown，连同 allowed_materials 打包到 WEBCLAUDE/模型装载部分/。
argument-hint: [公司名或代码，如 新乳业 / 002946]
allowed-tools: Read, Grep, Glob, Edit, Write, Bash
---

# /webload - 网页端 LOAD 打包器

`/webload` 是网页端执行 `/load` 的准备器。真正的模型理解仍由网页端 `/load` 完成；`/webload` 只负责先跑 deterministic prepare，然后把网页端需要的纪律、语法、边界和脚手架预合并成一个必读 Markdown。打包内容必须包含 `docs/knobs块契约.md`，作为网页端写末尾 `knobs` 机器自报清单的单一真源。

## 执行动作

1. 解析公司目录，接受公司名、裸代码、完整 ticker 或公司目录。
2. 定位 LOAD 模型素材，规则由 `src.model_load.prepare` 负责：

```text
companies\{公司}\Skills素材包\LOAD外部EXCEL模型理解器（一次最多一个）\
```

该目录必须恰好有一个 `.xlsx` / `.xlsm` / `.xls`，不再从 `active_vore`、`WEBCLAUDE` 或根目录寻找模型。

3. 运行：

```bash
py -m src.webload "{公司}" --overwrite
```

4. `src.webload` 会先创建：

```text
companies\{公司}\Agent\Load\{load_id}\
```

并写入 `model_boundary.*`、`forbidden_materials.md`、`allowed_materials/`、沙箱 `data_cutoff.db`、沙箱 `defaults.yaml`、`{原Excel文件名}_核心假设_load{YYYYMMDD}.md` 脚手架。

5. 然后清空并重建：

```text
companies\{公司}\WEBCLAUDE\模型装载部分\
```

## 打包清单

网页端包必须保持极简，只包含：

- `00_LOAD网页端合并执行包.md`
- `allowed_materials/`
- `webload_manifest.json`

`00_LOAD网页端合并执行包.md` 必须内嵌：

- `核心纪律_skill_vN.md`
- `核心假设源语言_skill_vN.md`
- `/load` 启动器的网页端运行摘要
- `model_boundary.md`
- `model_boundary.json`
- `forbidden_materials.md`
- `{原Excel文件名}_核心假设_load{YYYYMMDD}.md` 脚手架
- `模型装载器_skill_vN.md`

明确不打包：

- `data_cutoff.db`：留在本地 load 沙箱，供后续本地 `/comp` 和 DCF 使用。
- `load_manifest.json`：留在本地 load 沙箱；必要信息已经写入 `webload_manifest.json` 和合并执行包。
- `defaults.yaml`：留在本地 load 沙箱，供本地编译/DCF 使用。
- 单独的 `01_核心纪律`、`02_核心假设源语言`、`03_load启动器`、`04/05_model_boundary`、`06_forbidden_materials`、`07_核心假设脚手架`、`08_模型装载器` 阅读件。
- `forbidden_materials.md` 中列出的材料正文。
- 公司根目录旧正式核心假设。
- 正式 `Agent/forecast/`。

## 网页端怎么跑

把 `WEBCLAUDE/模型装载部分/` 上传到网页端后，先让网页端读 `00_LOAD网页端合并执行包.md`。

网页端必须遵守：

- 这是 `/load`，不是 `/ka`。
- 不再要求网页端逐个读取 A/B/启动器/边界/模型装载器；这些已经在合并执行包里。
- 模型时间轴最高权威。
- 不读取合并执行包禁读清单中列出的任何正文材料。
- 只读 `allowed_materials/`。
- 先给用户模型理解 overview，用户确认前不补完核心假设；overview 必须用会议 memo 风格，先讲你对模型的理解、预测、关键旋钮和风险，不要机械倾倒单元格和 knobs。
- 用户确认后，按时间轴 -> 收入 -> 毛利/成本 -> 费用 -> below-OP 与税 -> 中期/terminal 分段先押再问。
- 每段聊天里只给结论、紧凑表格和待拍板点；完整 `/comp` 源语言、历史原子、source range 和 `knobs` 块写进 `{原Excel文件名}_核心假设_load{YYYYMMDD}.md`。
- 输出必须是 `/comp` 源语言的 `{原Excel文件名}_核心假设_load{YYYYMMDD}.md`，末尾带 `knobs` 机器自报清单代码块。

网页端生成的 `{原Excel文件名}_核心假设_load{YYYYMMDD}.md` 放回 load manifest 中的 `core_assumption_path`。

然后本地继续编译 `yaml1_load_*.yaml` 并运行：

```bash
py -m src.model_load dcf --load-dir "companies\{公司}\Agent\Load\{load_id}" --yaml1 "<yaml1_load_path>"
```

## CLI

```bash
py -m src.webload 新乳业 --overwrite
py -m src.webload 002946 --overwrite
py -m src.webload 002946.SZ --overwrite
```

可选：

```bash
py -m src.webload 新乳业 --load-id xinruye_2025_vintage --overwrite
py -m src.webload 新乳业 --model "D:\path\model.xlsx" --overwrite
```

## 退出码

- `0`：成功。
- `2`：模型边界、公司解析或 load prepare 失败。
- `1`：其他 IO 异常。
