---
name: comp
description: 启动 yaml1 compiler：解析公司目录 → 先做年份门禁 → 动态加载最新版 yaml1compiler skill → 读取六份输入材料 → 通过信息保全/忠实度审计后编译生成 yaml1_公司名_YYYYMMDD.yaml → 自动跑 src.forecast 出 DCF。
argument-hint: [公司名或代码，如 新乳业 / 002946]
allowed-tools: Read, Grep, Glob, Edit, Write, Bash
---

# /comp — yaml1 compiler 启动器

把 `核心假设.md` 里分析师拍板的人话判断，编译成机器可读的 `yaml1_公司名_YYYYMMDD.yaml`，供下游 `forecast.py` 使用。`/comp` 不是研究员，也不是 DCF 试算器；它的第一职责是信息保全和忠实翻译。`/comp` 只编译**当前有效假设**：如果 `clean_annual` 最新实际年已经覆盖了核心假设的预测起点，必须先走 `/annual-update`。

## 执行顺序（必须遵守）

1. **解析公司目录**：接受完整 ticker / 裸代码 / 中文公司名。
2. **正式假设选择门（年份门禁前）**：
   - 只在公司根目录非递归寻找当前正式稿；排除 `*参考*.md`、`*draft*`、`Agent\`、`WEBCLAUDE\`、归档目录和任意子目录产物。
   - 候选文件必须在抬头声明 `状态: official`。若最新可见稿是 `状态: reference` / `状态: draft`，或只找到参考稿/草稿，**立即停止**，提示用户先完成 `/ka` 形成正式 `核心假设.md`。
   - `/load` 沙箱里的 `核心假设参考load_{YYYYMMDD}.md`、`model-extracted` 稿只能用于 load-vintage 沙箱编译，不能被本 `/comp` 当作公司当前正式假设。
3. **年份门禁（先于 compiler）**：
   - 使用上一步选中的正式核心假设，并找到 `Agent\data.db`、`Agent\defaults.yaml`。
   - 若 `Agent\data.db` 存在，先运行：
     ```bash
     py -m src.assumption_staleness --company-dir "companies/{公司名}_{代码}"
     ```
   - 若退出码为 `2`，表示 `clean_annual` 最新实际年已经覆盖核心假设预测起点，或 `defaults.yaml` 基期落后于最新实际年。**立即停止 `/comp`**，原样报告 stdout，并提示用户先跑 `/annual-update {公司}`。不要加载 compiler、不要生成新 yaml1、不要跑 DCF。
   - 若 `Agent\data.db` 不存在，年份门禁无法执行；允许继续编译 yaml1，但第六步 DCF 仍按「缺 data.db」规则跳过。
4. **动态加载最新版 yaml1compiler skill**：扫描 `D:\MKA\skills\`，匹配 `yaml1compiler_v*.md`，取版本号最大的那份。**必须先通过年份门禁，再加载 compiler，再读输入材料**，防止注意力涣散。
5. **读取六份输入材料**：
   - 第二步选中的公司根目录 `状态: official` 核心假设（语义层：判断、历史、旋钮、时间轴、覆盖项）
   - `companies\{公司}\Agent\defaults.yaml`（目标命名空间：覆盖落到哪些真实路径）
   - `D:\MKA\docs\数据格式参考.md`（字典：中文科目 ↔ TuShare 字段语义对齐）
   - `D:\MKA\docs\yaml1算法模板契约.md`（算法硬边界：cleaner/calc 支持的模板清单）
   - `D:\MKA\docs\knobs块契约.md`（解释核心假设末尾 `knobs` 机器自报清单；fidelity block-diff 的单一真源）
   - `D:\MKA\docs\yaml1前端展示契约.md`（解释 `display` 展示语义；决定 B 类 stash 在主表、副拆分、Reference 中的去向）
   - **副拆分毛利率/同比自动提取**：跑 `py scripts/dump_secondary_metrics.py "companies\{公司}_{代码}"`，它从 /init 产物 `Agent\OfficialBreakdowns\business_revenue_breakdown.csv` 直接提取各 dimension（地区/渠道/产品/行业）的收入+毛利率+同比成 yaml 片段（毛利率/同比直接拿，不算）。编译 stash 副拆分块时，把脚本输出里与 .md 收纳区副拆分块同 dimension 的 毛利率/同比 series 注入对应块（保留 .md 的 note/caveat，只补 毛利率/同比 子块）；与主拆分 leaf 重叠的 dimension（如"按产品"=主拆分）不进 stash。无 breakdown CSV 的公司该项缺，前端自动不渲染，不报错。详见 `yaml1compiler_v5.md` §6.2。
   - 读取后先做时间轴预判：`meta.horizon` 永远取核心假设/knobs 块里的**显式预测期年轴**，不是完整 DCF 年轴；完整 forecast 年轴由 `terminal.explicit_end == meta.horizon[-1]` 与 `terminal.fade.to_year` 交给 cleaner 展开。不要为确认这个惯例去读取旧 yaml1 产物。
   - 若源文写了衰减期里某个非收入增速路径要到具体目标值（如 `income.gpm` 从 31.1% 到 32.0%、某个绝对值项到 -40M），使用 `terminal.fade.path_targets`；只有明确维持不变的路径才进 `hold_paths`。
   - 同时遵守 `D:\MKA\docs\核心假设翻译IR契约.md`。它是 Semantic IR 翻译账本契约，不算公司输入材料，不改变“六份输入材料”的口径。
   - 若分不清 B 类去向、BS/CF 例外、命令边界或该读哪份契约，查 `D:\MKA\docs\MKA规则导航图.md`。它是索引，不算公司输入材料，不改变“六份输入材料”的口径。
6. **按加载到的 compiler skill 执行编译与审计**：先按 Semantic IR 盘点 `源文块识别 -> IR 分类 -> yaml1 落点 -> audit 六段`，再生成 yaml1，输出到 `companies\{公司}\Agent\yaml1_公司名_YYYYMMDD.yaml`（日期 = 本次编译日 `YYYYMMDD`），并执行 `yaml1compiler` §9 的 compiler audit。
7. **自动跑 DCF**：只有 compiler audit 判定 `audit_clean` 后，才允许调 `src.forecast` 跑正式 DCF。详见下方「第七步：自动 DCF」。

## 重要纪律

- **与 A/B 的关系**:compiler 翻译 `核心假设.md`(用 `核心假设源语言_skill`(B) 的形状写成)到 yaml1;不写 `核心假设.md`,故不加载 A(写作纪律),但需理解 B(形状)才能忠实翻译。
- **Semantic IR 不是新产物**：IR 是翻译账本和审计模型，不落成强制 JSON，不成为第三份可编辑事实源。`核心假设.md` 仍是 canonical，yaml1 仍是派生缓存。
- **年份门禁是选定正式稿后的第一件事**：只要 `clean_annual` 已有 2025 实际、核心假设仍从 2025 开始预测，就不能继续 `/comp`；这不是 compiler 错误，而是应该走 `/annual-update`。
- **`/comp` 只吃正式稿**：参考稿、草稿、`/load` 沙箱稿和 `model-extracted` 稿都不能静默成为正式 forecast 的源文。
- **compiler audit 是 official forecast 门禁**：覆盖双射、B 类完整性、`unaligned`/路径待核、语义待核、主动覆盖回读都清干净，才叫 `audit_clean`；否则 yaml1 只能作为 reference/draft 产物保存，不跑 official forecast。
- **信息保全闸**：A 类进入可计算覆盖，B 类进入 `history` / `stash` / `display`，歧义进入 `unaligned` 或待核清单；三者都清楚，才允许进入 official forecast。DCF 能跑不是唯一成功标准，信息没有丢才是。
- **所有 skill 均不读取 PDF。** 如果 `核心假设.md` 的来源材料里有 PDF，compiler 只信任已经被翻译进 `.md` 的内容。
- `defaults.yaml` 是目标命名空间，不是输入假设；compiler 负责把 `核心假设.md` 里的覆盖项落到 `defaults.yaml` 已有的真实路径上。
- `docs/数据格式参考.md` 和 `docs/yaml1算法模板契约.md` 是只读契约，compiler 不能改写。
- `display` 是前端展示契约，不改变 DCF。新产物应生成或保留顶层 `display`；缺失时 workbench 只会走保守推断，不能替代 compiler 的明确声明。

## 输出文件命名

```
companies/{公司名}_{代码}/Agent/yaml1_公司名_YYYYMMDD.yaml
```

例如：`companies/新乳业_002946/Agent/yaml1_新乳业_20250616.yaml`

## 第七步：自动 DCF（compiler audit clean 后执行）

yaml1 是 comp 的主产物，但**不是落盘即 official 成功**。落盘后必须先输出 compiler audit report；只有 `audit_clean` 才能自动跑一次正式 DCF，让用户拿到完整的 `Agent/forecast/`，不必再手动敲 `src.forecast`。

汇报口吻要像 compiler 审计 memo，不像机器日志：先讲“这份核心假设被成功翻译成了什么 / 哪些覆盖项生效 / 哪些路径或语义被拦住 / DCF 是否跑通”，再给关键文件路径。不要把 stdout、yaml1 大段内容或 audit JSON 原样倾倒给用户；失败时只摘关键错误和下一步。

### Compiler Audit / 信息保全门禁（不干净则不跑 DCF）

报告必须使用固定结构，少项视为 audit 不完整：

1. **A 类覆盖**：`.md` 每条可计算旋钮/结构判断都被 yaml1 认领，无漏无多。
2. **B 类保全**：leaf history、stash、display 去向与源文对齐，收纳区没有丢失或塞错位置。
3. **路径待核**：`unaligned` / `# 路径待核` 必须为空；否则 yaml1 只能标 reference/draft。
4. **语义待核**：`# 语义待核` 必须为空，或已经被分析师显式确认；未确认则不跑 official forecast。
5. **主动覆盖回读**：主动覆盖项已用人话回读完成，且没有未拍板项。
6. **Forecast 状态**：`not_run` / `skipped_missing_data` / `ran_ok` / `failed_after_audit_clean`，并说明 `Agent/forecast/` 是否被覆盖。

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
