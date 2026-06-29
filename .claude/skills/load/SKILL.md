---
name: load
description: 启动 LOAD 外部 Excel 模型理解器。只读取公司 Skills素材包/LOAD外部EXCEL模型理解器（一次最多一个）里的唯一 Excel，先建立 load 沙箱与时间边界，再按核心纪律 A 与核心假设源语言 B 把模型公式层翻译为 /comp 能继续 schema 化的 `{原Excel文件名}_核心假设_load{YYYYMMDD}.md`。产物是 load-vintage，不回退到 KA。
argument-hint: [公司名或代码，如 新乳业 / 002946]
allowed-tools: Read, Grep, Glob, Edit, Write, Bash
---

# /load - 外部 Excel 模型理解器

`/load` 把一个外部 Excel 模型翻译成 `/comp` 能继续 schema 化的核心假设源文。只保存原模型 load-vintage，不生成当前正式判断，不接管 `/ka` 裁决。

本启动器只负责**启动机械**：解析目录 → 素材入口（唯一 Excel）→ deterministic prepare（建沙箱+时间边界）→ 加载 runbook → 拉起沙箱。**理解流程（核心边界、Excel 公式层读法、overview 确认门、源语言写法、停止条件）在模型装载器 runbook**（`模型装载器_skill_v*.md`），不在本文件重复——读到那里照做。`/load` 的产出止于核心假设参考 markdown，不编译 yaml1、不跑 DCF。

与历史 v19（已归档至 `deprecatedlogs/`）的关系：读模型能力已迁到 `/load`；当前核心假设裁决留给 `/ka`。横切纪律以 `核心纪律_skill`(A1-A7) + `核心假设源语言_skill`(B) 为准，不引用旧 v19。

**主导方向**：保真装载业务拆分+历史+收纳数据（即便不参与计算）优先于搬运预测；详见 runbook 核心指导。

## 0. 共享真源

执行任何阅读和写作前，必须先加载：

```text
D:\MKA\skills\核心纪律_skill_v*.md
D:\MKA\skills\核心假设源语言_skill_v*.md
D:\MKA\docs\knobs块契约.md
D:\MKA\skills\模型装载器_skill_v*.md          # /load 理解流程 runbook
```

`/load` 完整继承核心纪律 A1-A7；输出符合核心假设源语言 B，末尾 `model-extracted` knobs 块语法以 `docs/knobs块契约.md` 为准。核心边界（load-vintage 隔离、forbidden_materials 沙箱、权威顺序、装载范围只限利润表）、Excel 读法、overview 门、源语言写法、停止条件——全见 runbook。

## 1. 解析公司目录

从 `$ARGUMENTS` 定位 `D:\MKA\companies\{公司}`：

1. 精确匹配 `companies\{参数}`。
2. 代码匹配 `companies\*_{代码}`，如 `002946`。
3. 公司名匹配 `companies\{公司名}_*`。
4. 命中多个时列候选并询问用户。
5. 未命中时报错停止。

## 2. 定位 LOAD 素材入口

只从固定素材包读取模型：

```text
companies\{公司}\Skills素材包\LOAD外部EXCEL模型理解器（一次最多一个）\
```

硬规则：

- 该文件夹必须恰好有一个 `.xlsx` / `.xlsm` / `.xls`。
- 跳过 Office lock 文件 `~$*.xls*`。
- 没有 Excel 时停止，提示用户把模型放入该文件夹。
- 多于一个 Excel 时停止，列出文件名，让用户只保留一个。
- 不从 `active_vore`、`WEBCLAUDE`、公司根目录或正式 `Agent/forecast` 寻找模型。

## 3. 先跑 deterministic prepare

在 AI 阅读材料、年报、数据库、旧核心假设之前，先运行：

```bash
py -m src.model_load prepare "{公司}" --overwrite
```

prepare 是 `/load` 的"时间轴第零件事"。它会：

1. 用 `openpyxl(data_only=False)` 读取公式层。
2. 锁定模型边界：`model_asof_date` / `history_end_year` / `forecast_start_year` / `forecast_years`。
3. 创建沙箱：

```text
companies\{公司}\Agent\Load\{load_id}\
```

4. 写入：
   - `model_boundary.json` / `model_boundary.md`
   - `allowed_materials\`
   - `forbidden_materials.md`
   - `data_cutoff.db`（若正式 `Agent\data.db` 存在）
   - `defaults.yaml`（若 `data_cutoff.db` 可生成）
   - `{原Excel文件名}_核心假设_load{运行YYYYMMDD}.md` 脚手架（沙箱内，仅供装载器续写/同步）
   - `root_core_assumption_path`：最终主产物应回填到公司根目录的路径

如果 prepare 报时间轴冲突、base period 冲突、Excel 数量异常或无法建立沙箱，必须停止并报告，不允许绕过。

## 4. 先加载模型装载器 skill，再读沙箱

扫描并读取最新版本（按 `vN` 的 N 做整数比较取最大，不是字符串排序）：

```text
D:\MKA\skills\模型装载器_skill_v*.md
```

必须先加载模型装载器 skill，再开始 AI 阅读沙箱材料。**读取纪律、确认顺序、Excel 公式层读法、overview 确认门、输出格式、停止条件都由该 runbook 定义**——本启动器 §5 把沙箱拉起来后，进入 runbook 走理解流程，产出核心假设参考 markdown 即止。

不要把已归档的旧 v19（`deprecatedlogs/04_核心假设生成修改器_skill_v19.md`）当主流程。

## 5. 只读 load 沙箱，不读越界材料

AI 只允许读取：

```text
Agent\Load\{load_id}\model_boundary.md
Agent\Load\{load_id}\model_boundary.json
Agent\Load\{load_id}\allowed_materials\
```

`forbidden_materials.md` 只能作为禁读清单读取，禁止打开其中列出的正文材料。沙箱禁读边界与越界材料清单见 runbook §3。

## 6. 主产物与沙箱副本路径

同步纪律（两份一字不差）、单写源方向的**单一真源是模型装载器 runbook §1/§5/§7**（`模型装载器_skill_v*.md`），本启动器不重抄同步纪律，只钉写落点：主产物写 KA 参考稿区 `companies\{公司}\Skills素材包\KA（ALPHAPAI拆出来的东西放在这里）\核心假设参考load_{运行YYYYMMDD}.md`（供 `/ka` 读取，前缀不可省略），同步副本写 `companies\{公司}\Agent\Load\{load_id}\核心假设参考load_{运行YYYYMMDD}.md`。脚手架在沙箱、AI 续写改沙箱、定稿后同步到 KA 参考稿区。overview 确认门、源语言写法、各段逐段写法见 runbook §6-§7。

## 7. CLI

```bash
/load 新乳业
/load 002946
/load 002946.SZ
```

> 注：底层 `src.model_load` 用 `prepare` 子命令（`py -m src.model_load prepare "{公司}" --overwrite`），与 `src.brkd_prepare`/`src.webload`/`src.ka_prepare` 等无子命令的 CLI 风格不同——model_load 是唯一带子命令的 prepare 模块；`/webload` 内部直接复用 `prepare_load` 函数、不走子命令。

## 8. 退出码

- `0`：根目录主产物 `核心假设参考load_{YYYYMMDD}.md` 生成成功（沙箱副本同步）。
- `2`：输入无法解析为唯一公司目录，或素材包 Excel 数量异常，或 `src.model_load prepare` 失败。
- `3`：沙箱 `defaults.yaml` 的 `base_period` 不等于 `history_end_year`，或时间边界冲突。
- `1`：其他 IO 异常。
