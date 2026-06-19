---
name: comp
description: 启动 yaml1 compiler：解析公司目录 → 动态加载最新版 yaml1compiler skill → 读取四份输入材料 → 编译生成 yaml1_公司名_YYYYMMDD.yaml → 自动跑 src.forecast 出 DCF。
argument-hint: [公司名或代码，如 新乳业 / 002946]
allowed-tools: Read, Grep, Glob, Edit, Write, Bash
---

# /comp — yaml1 compiler 启动器

把 `核心假设.md` 里分析师拍板的人话判断，编译成机器可读的 `yaml1_公司名_YYYYMMDD.yaml`，供下游 `forecast.py` 使用。

## 执行顺序（必须遵守）

1. **解析公司目录**：接受完整 ticker / 裸代码 / 中文公司名。
2. **动态加载最新版 yaml1compiler skill**：扫描 `D:\MKA\skills\`，匹配 `yaml1compiler_v*.md`，取版本号最大的那份。**必须先加载 compiler，再读输入材料**，防止注意力涣散。
3. **读取四份输入材料**：
   - `companies\{公司}\*核心假设*.md` 中最新一份（语义层：判断、历史、旋钮、时间轴、覆盖项）
   - `companies\{公司}\defaults.yaml`（目标命名空间：覆盖落到哪些真实路径）
   - `D:\MKA\docs\数据格式参考.md`（字典：中文科目 ↔ TuShare 字段语义对齐）
   - `D:\MKA\docs\yaml1算法模板契约.md`（算法硬边界：cleaner/calc 支持的模板清单）
4. **按加载到的 compiler skill 执行编译**，生成 yaml1，输出到 `companies\{公司}\yaml1_公司名_YYYYMMDD.yaml`（日期 = 本次编译日 `YYYYMMDD`）。
5. **自动跑 DCF**：yaml1 落盘后立即调 `src.forecast`，把每股价值报告给用户。详见下方「第五步：自动 DCF」。

## 重要纪律

- **所有 skill 均不读取 PDF。** 如果 `核心假设.md` 的来源材料里有 PDF，compiler 只信任已经被翻译进 `.md` 的内容。
- `defaults.yaml` 是目标命名空间，不是输入假设；compiler 负责把 `核心假设.md` 里的覆盖项落到 `defaults.yaml` 已有的真实路径上。
- `docs/数据格式参考.md` 和 `docs/yaml1算法模板契约.md` 是只读契约，compiler 不能改写。

## 输出文件命名

```
companies/{公司名}_{代码}/yaml1_公司名_YYYYMMDD.yaml
```

例如：`companies/新乳业_002946/yaml1_新乳业_20250616.yaml`

## 第五步：自动 DCF（yaml1 落盘后立即执行）

yaml1 是 comp 的主产物，落盘即成功。落盘后**立即**自动跑一次 DCF，让用户拿到完整的 `forecast/`，不必再手动敲 `src.forecast`。

### 前置检查（缺则跳过 DCF，但仍算 comp 成功）

- `companies\{公司}\data.db` 必须存在——`src.forecast` 要读 `clean_annual`。缺则**跳过 DCF**，提示用户："缺 data.db，请先跑 `/init {公司}` 或 `py -m src.clean --ticker {代码}` 生成 clean 表，再手动 `py -m src.forecast --yaml1 <刚写的 yaml1>`。"yaml1 已落盘，comp 退出码仍为 0。

### 执行命令

在项目根目录 `D:\MKA` 下运行（Bash 工具 cwd 即为 D:\MKA）：

```bash
py -m src.forecast --yaml1 "companies/{公司名}_{代码}/yaml1_{公司名}_{YYYYMMDD}.yaml"
```

- **用 `--yaml1` 而非 `--ticker`**：comp 可能被中文名/裸代码调用，`--yaml1` 直接用刚写出的产物定位 company_dir，免推断交易所后缀，最稳。`forecast.py` 会据此自动取 `company/defaults.yaml` 和 `company/data.db`。
- **覆盖保证**：`src.forecast` 内部 `reset_forecast_dir` 会先 `rmtree` 整个 `forecast/` 再重写，旧 DCF 自动覆盖，无需 comp 处理。
- **Python 路径**：用 `py` 启动器（项目约定），不要用 bare `python`（WindowsApps 占位符会静默无输出）。

### 结果汇报

命令成功（退出码 0）：把 stdout 里的 **每股价值（per_share_value）、warnings 数、`forecast/` 路径**报告给用户，并提示详细 DCF 在 `forecast/dcf_detail.csv` + `dcf_summary.json`，清洗审计在 `.modelking/yaml1_clean_report.json`。

命令失败（非 0 退出）：**yaml1 仍算编译成功**（产物已落盘，不回滚），但**显式上报 DCF 错误**——把 stderr/异常原样摆出来，指明排查方向：
- 路径/符号/模板错 → 看 `.modelking/yaml1_clean_report.json` 的 errors/warnings，回 yaml1 修正后重跑 `/comp`。
- 配平/计算错 → 看 `src.forecast` 抛出的 CalcError 栈。
comp 退出码仍为 0（yaml1 成功），DCF 错误仅为上报，不改变 comp 成功结论。

## CLI

```bash
/comp 新乳业
/comp 002946
/comp 002946.SZ
```

## 退出码

- `0`：yaml1 编译成功（主产物已落盘）。第五步自动 DCF 的成败**不影响**此结论——DCF 成功则顺带报告每股价值，失败/跳过则显式上报错误，但 comp 仍为 0。
- `2`：输入无法解析为唯一公司目录
- `3`：缺少 `核心假设.md` 或 `defaults.yaml`
- `1`：compiler 执行异常或其他 IO 错误（yaml1 未生成）
