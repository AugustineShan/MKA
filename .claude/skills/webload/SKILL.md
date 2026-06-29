---
name: webload
description: 一键准备 /load 时间沙箱，并把网页端执行 /load 所需的共享纪律、核心假设源语言、load 运行纪律、边界、禁读清单、模型装载器和 `核心假设参考load_{YYYYMMDD}.md` 脚手架预合并成一个 Markdown，连同 allowed_materials 打包到 WEBCLAUDE/模型装载部分/。
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

并写入 `model_boundary.*`、`forbidden_materials.md`、`allowed_materials/`、沙箱 `data_cutoff.db`、沙箱 `defaults.yaml`、`核心假设参考load_{YYYYMMDD}.md` 脚手架。

5. 然后清空并重建：

```text
companies\{公司}\WEBCLAUDE\模型装载部分\
```

## 打包清单

网页端包只包含（单文件合并 + allowed_materials 目录）：

- `00_LOAD网页端合并执行包.md`
- `allowed_materials/`
- `webload_manifest.json`（供本地 `--load-id` 复用与审计，网页端不读 json）

`00_LOAD网页端合并执行包.md` 必须内嵌：

- `核心纪律_skill_vN.md`
- `核心假设源语言_skill_vN.md`
- `/load` 启动器的网页端运行摘要
- `model_boundary.md`
- `model_boundary.json`
- `forbidden_materials.md`
- `核心假设参考load_{YYYYMMDD}.md` 脚手架
- `模型装载器_skill_vN.md`

明确不打包：

- `data_cutoff.db`：留在本地 load 沙箱，不再供 `/load` 编译/DCF（`/load` 已止于 markdown）。
- `load_manifest.json`：留在本地 load 沙箱；必要信息已经写入 `webload_manifest.json` 和合并执行包。
- `defaults.yaml`：留在本地 load 沙箱，留作后续流程备用，`/load` 本身不消费。
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
- 每段聊天里只给结论、紧凑表格和待拍板点；完整 `/comp` 源语言、历史原子、source range 和 `knobs` 块写进 `核心假设参考load_{YYYYMMDD}.md`。
- 输出必须是 `/comp` 源语言的 `核心假设参考load_{YYYYMMDD}.md`，末尾带 `knobs` 机器自报清单代码块。

网页端生成的 `核心假设参考load_{YYYYMMDD}.md` 路径与同步纪律（沙箱 `core_assumption_path` ↔ KA 参考稿区 `root_core_assumption_path`，两份一字不差）的单一真源是模型装载器 runbook §1/§5/§7，本启动器不重抄。`/webload` 与 `/load` 一样止于此 markdown，不编译 `yaml1_load`、不跑 DCF；若要变成当前正式 forecast，另走 `/ka` → `/comp`。

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
