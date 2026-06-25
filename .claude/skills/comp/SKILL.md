---
name: comp
description: 启动 yaml1 compiler：解析公司目录 → 先做年份门禁 → 动态加载最新版 yaml1compiler skill → 读取四份输入材料 → 编译生成 yaml1_公司名_YYYYMMDD.yaml → 自动跑 src.forecast 出 DCF。
argument-hint: [公司名或代码，如 新乳业 / 002946]
allowed-tools: Read, Grep, Glob, Edit, Write, Bash
---

# /comp — yaml1 compiler 启动器

把 `核心假设.md` 里分析师拍板的人话判断，编译成机器可读的 `yaml1_公司名_YYYYMMDD.yaml`，供下游 `forecast.py` 使用。`/comp` 只编译**当前有效假设**：如果 `clean_annual` 最新实际年已经覆盖了核心假设的预测起点，必须先走 `/annual-update`。

## 执行顺序（必须遵守）

1. **解析公司目录**：接受完整 ticker / 裸代码 / 中文公司名。
2. **正式假设选择门（年份门禁前）**：
   - 只在公司根目录非递归寻找当前正式稿；排除 `*参考*.md`、`*draft*`、`Agent\`、`WEBCLAUDE\`、归档目录和任意子目录产物。
   - 候选文件必须在抬头声明 `状态: official`。若最新可见稿是 `状态: reference` / `状态: draft`，或只找到参考稿/草稿，**立即停止**，提示用户先完成 `/ka` 形成正式 `核心假设.md`。
   - `/load` 沙箱里的 `{原Excel文件名}_核心假设.md`、`model-extracted` 稿只能用于 load-vintage 沙箱编译，不能被本 `/comp` 当作公司当前正式假设。
3. **年份门禁（先于 compiler）**：
   - 使用上一步选中的正式核心假设，并找到 `Agent\data.db`、`Agent\defaults.yaml`。
   - 若 `Agent\data.db` 存在，先运行：
     ```bash
     py -m src.assumption_staleness --company-dir "companies/{公司名}_{代码}"
     ```
   - 若退出码为 `2`，表示 `clean_annual` 最新实际年已经覆盖核心假设预测起点，或 `defaults.yaml` 基期落后于最新实际年。**立即停止 `/comp`**，原样报告 stdout，并提示用户先跑 `/annual-update {公司}`。不要加载 compiler、不要生成新 yaml1、不要跑 DCF。
   - 若 `Agent\data.db` 不存在，年份门禁无法执行；允许继续编译 yaml1，但第六步 DCF 仍按「缺 data.db」规则跳过。
4. **动态加载最新版 yaml1compiler skill**：扫描 `D:\MKA\skills\`，匹配 `yaml1compiler_v*.md`，取版本号最大的那份。**必须先通过年份门禁，再加载 compiler，再读输入材料**，防止注意力涣散。
5. **读取四份输入材料**：
   - 第二步选中的公司根目录 `状态: official` 核心假设（语义层：判断、历史、旋钮、时间轴、覆盖项）
   - `companies\{公司}\Agent\defaults.yaml`（目标命名空间：覆盖落到哪些真实路径）
   - `D:\MKA\docs\数据格式参考.md`（字典：中文科目 ↔ TuShare 字段语义对齐）
   - `D:\MKA\docs\yaml1算法模板契约.md`（算法硬边界：cleaner/calc 支持的模板清单）
6. **按加载到的 compiler skill 执行编译与审计**，生成 yaml1，输出到 `companies\{公司}\Agent\yaml1_公司名_YYYYMMDD.yaml`（日期 = 本次编译日 `YYYYMMDD`），并执行 `yaml1compiler` §9 的 compiler audit。
7. **自动跑 DCF**：只有 compiler audit 判定 `audit_clean` 后，才允许调 `src.forecast` 跑正式 DCF。详见下方「第七步：自动 DCF」。

## 重要纪律

- **年份门禁是选定正式稿后的第一件事**：只要 `clean_annual` 已有 2025 实际、核心假设仍从 2025 开始预测，就不能继续 `/comp`；这不是 compiler 错误，而是应该走 `/annual-update`。
- **`/comp` 只吃正式稿**：参考稿、草稿、`/load` 沙箱稿和 `model-extracted` 稿都不能静默成为正式 forecast 的源文。
- **compiler audit 是 official forecast 门禁**：覆盖双射、B 类完整性、`unaligned`/路径待核、语义待核、主动覆盖回读都清干净，才叫 `audit_clean`；否则 yaml1 只能作为 reference/draft 产物保存，不跑 official forecast。
- **所有 skill 均不读取 PDF。** 如果 `核心假设.md` 的来源材料里有 PDF，compiler 只信任已经被翻译进 `.md` 的内容。
- `defaults.yaml` 是目标命名空间，不是输入假设；compiler 负责把 `核心假设.md` 里的覆盖项落到 `defaults.yaml` 已有的真实路径上。
- `docs/数据格式参考.md` 和 `docs/yaml1算法模板契约.md` 是只读契约，compiler 不能改写。

## 输出文件命名

```
companies/{公司名}_{代码}/Agent/yaml1_公司名_YYYYMMDD.yaml
```

例如：`companies/新乳业_002946/Agent/yaml1_新乳业_20250616.yaml`

## 第七步：自动 DCF（compiler audit clean 后执行）

yaml1 是 comp 的主产物，但**不是落盘即 official 成功**。落盘后必须先输出 compiler audit report；只有 `audit_clean` 才能自动跑一次正式 DCF，让用户拿到完整的 `Agent/forecast/`，不必再手动敲 `src.forecast`。

### Compiler Audit 门禁（不干净则不跑 DCF）

报告必须至少覆盖：

- 覆盖双射：`.md` 每条 A 类旋钮/结构判断都被 yaml1 认领，无漏无多。
- B 类完整性：leaf history 与 `stash` 对齐源文，收纳区没有丢失或塞错位置。
- `unaligned` / 路径待核：必须为空；否则 yaml1 只能标 reference/draft。
- 语义待核：必须为空，或已经被分析师显式确认；未确认则不跑 official forecast。
- 主动覆盖人话回读：已完成，且没有未拍板的主动覆盖项。

若 compiler audit 不干净：可以保留 `yaml1_*.yaml` 作为参考产物，但必须在汇报里标明 `reference yaml1`，停止 `/comp` 的 official forecast，不得运行 `src.forecast` 去覆盖 `Agent/forecast/`。

### 前置检查（缺则跳过 DCF，但仍算 comp 成功）

- `companies\{公司}\Agent\data.db` 必须存在——`src.forecast` 要读 `clean_annual`。缺则**跳过 DCF**，提示用户："缺 data.db，请先跑 `/init {公司}` 或 `py -m src.clean --ticker {代码}` 生成 clean 表，再手动 `py -m src.forecast --yaml1 <刚写的 yaml1>`。"yaml1 已落盘且 audit clean 时，编译/审计可视为成功，但 forecast 未执行。
- `src.forecast` 内部也有同一套年份硬门禁。如果这里报 `需要先运行 /annual-update`，说明刚写出的 yaml1 或 defaults 基期仍旧；yaml1 已落盘但**不能作为正式 DCF**，必须先完成年度更新再重跑 `/comp`。

### 执行命令

在项目根目录 `D:\MKA` 下运行（Bash 工具 cwd 即为 D:\MKA）：

```bash
py -m src.forecast --yaml1 "companies/{公司名}_{代码}/Agent/yaml1_{公司名}_{YYYYMMDD}.yaml"
```

- **用 `--yaml1` 而非 `--ticker`**：comp 可能被中文名/裸代码调用，`--yaml1` 直接用刚写出的产物定位 company_dir，免推断交易所后缀，最稳。`forecast.py` 会据此自动取 `company/Agent/defaults.yaml` 和 `company/Agent/data.db`。
- **覆盖保证**：`src.forecast` 内部 `reset_forecast_dir` 会先 `rmtree` 整个 `Agent/forecast/` 再重写，旧 DCF 自动覆盖，无需 comp 处理。
- **Python 路径**：用 `py` 启动器（项目约定），不要用 bare `python`（WindowsApps 占位符会静默无输出）。

### 结果汇报

命令成功（退出码 0）：把 stdout 里的 **每股价值（per_share_value）、warnings 数、`Agent/forecast/` 路径**报告给用户，并提示详细 DCF 在 `Agent/forecast/dcf_detail.csv` + `dcf_summary.json`，清洗审计在 `Agent/.modelking/yaml1_clean_report.json`。

命令失败（非 0 退出）：若 compiler audit 已经 clean，**yaml1 编译/审计仍算成功**（产物已落盘，不回滚），但**显式上报 DCF 错误**——把 stderr/异常原样摆出来，指明排查方向：
- 路径/符号/模板错 → 看 `Agent/.modelking/yaml1_clean_report.json` 的 errors/warnings，回 yaml1 修正后重跑 `/comp`。
- 配平/计算错 → 看 `src.forecast` 抛出的 CalcError 栈。
comp 退出码仍为 0（yaml1 编译且 audit_clean），DCF 错误仅为上报，不改变 comp 编译/审计成功结论。

## CLI

```bash
/comp 新乳业
/comp 002946
/comp 002946.SZ
```

## 退出码

- `0`：yaml1 编译成功且 compiler audit clean（主产物已落盘，可作为 official forecast 输入）。第七步自动 DCF 的成败**不影响**此结论——DCF 成功则顺带报告每股价值，失败/跳过则显式上报错误，但 comp 仍为 0。
- `2`：输入无法解析为唯一公司目录
- `3`：缺少 `核心假设.md` 或 `defaults.yaml`
- `4`：yaml1 已生成但 compiler audit 不干净（存在 `unaligned`、路径待核、未确认语义待核、B 类缺失或主动覆盖未回读）；仅为 reference/draft yaml1，不跑 official forecast
- `1`：compiler 执行异常或其他 IO 错误（yaml1 未生成）
