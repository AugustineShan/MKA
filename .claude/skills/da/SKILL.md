---
name: da
description: 启动重资产折旧摊销排程生成流程。解析公司目录 → 读取定调材料 → 动态加载最新版 da 执行细则 → 三阶段(并行事实抽取 da_facts → 先押再问商议 da_schedule → 落盘 Agent/da_schedule.yaml)。产物 enabled 后 src.forecast 自动消费 da_series 驱动重资产 DCF。
argument-hint: [公司名或代码，如 新乳业 / 002946]
allowed-tools: Read, Grep, Glob, Edit, Write, Bash
---

# /da — 重资产折旧摊销排程启动器

重资产公司的 DA+capex 专用通道。把年报里人啃不动的固定资产/在建工程/无形资产附注扒干净,和分析师商议出未来 capex 排程与转固节奏,落 `Agent/da_schedule.yaml`。`enabled: true` 后 `src.forecast` 自动消费 da_series 驱动重资产 DCF(分类别年限 cohort 滚动 + 转固时滞 + 终值稳态)。

**不该用**:轻资产、稳态、defaults 的 `capex_pct`+`depr_rate` 已够用的公司(把简单问题复杂化)。

## 第一动作:解析公司目录

从 `$ARGUMENTS` 解析公司,在 `D:\MKA\companies\` 下定位目录:

1. 精确匹配 `companies\{参数}` → 直接命中。
2. 代码(如 `002946`)→ 匹配 `companies\*_{参数}`。
3. 公司名(如 `新乳业`)→ 匹配 `companies\{参数}_*`。
4. 命中多个 → 列出候选,问用户。
5. 未命中 → 问用户。

## 第二动作:立刻读取同权重定调材料

公司目录定位后,**在读取任何其他材料之前**,先读取:

```
py -m src.ka_prepare "{公司}"
companies\{公司}\Skills素材包\最高权重材料-放Agent最应对齐的材料\markdown存储区\
```

**这不是"又一份待读材料"。** `公司判断和最新观点.md` 是分析师唯一手写的判断源,`companies\{公司}\重要文件\` 下材料与它同等权重（常放最重要、最新的会议纪要）,共同构成本次工作的**定调材料**。它们里面写的核心 thesis、关键假设、关注点和口径选择,就是"老板交代的视角"。后续读年报附注、商议 capex 时,全部放在它们的框架下解读,不要另起炉灶、不要和它们的定调打架。manifest 中 `unsupported/error` 必须进入缺口区。

如果 `公司判断和最新观点.md` 不存在或 `ka_prepare` 失败 → **报错停止**,告诉用户:"缺少公司判断和最新观点.md 或同权重定调材料准备失败,请先准备。它是本次工作的定调材料,没有它无法启动 /da。"

**业务预理解参考(若存在)**:读 `companies\{公司}\Agent业务讨论.md`(由 `/brkd` 产出)。若存在,capex 商议第三点(扩张性 capex)时可用其产能/项目线索作起点,但 headline 须用年报/clean_annual 校验。

## 第三动作:判断 init / modify 模式

Glob **非递归**检查 `companies\{公司}\Agent\da_schedule.yaml`:

- 存在 → **modify 模式**,读取现有底稿。**记下这份 base 旧底稿的完整路径**(落盘时要先归档它,见第三阶段)。
- 不存在 → **init 模式**。

**只认 `Agent\da_schedule.yaml` 这一个文件**(`da_schedule_path(company_dir)` 的契约)。禁止递归扫子目录(如 `Agent\DAhistory\` 是归档区,不能当现有底稿)。

## 第四动作:动态加载最新版 da 执行细则

扫描 `D:\MKA\skills\`,找到匹配 `da_折旧摊销排程_skill_v*.md` 的文件中**版本号最大**的那一份。

例如同时存在:

- `da_折旧摊销排程_skill_v1.md`
- `da_折旧摊销排程_skill_v2.md`

则取 v2。

读取该文件,作为本次工作的执行细则指令。

## 第五动作:进入执行细则流程

现在你已经拥有:

- 同权重定调材料(最先读: 公司判断和最新观点.md + 重要文件/ + manifest)
- 现有 da_schedule 底稿(modify 模式)
- 最新版 da 执行细则 skill

接下来按加载到的那份执行细则执行三阶段:

1. **并行事实抽取** → `Agent\recon\da_facts_latest.json`(事实层,LLM 扒年报附注,只填表不推算,抽不到留 null)。
2. **商议协议** → `Agent\da_schedule.yaml`(假设层,先押再问拍板才落盘)。
3. **落盘与收口** → 提示用户重跑 `py -m src.forecast --ticker {代码}` 触发重资产 DCF。

人机商议必须用会议 memo 风格：先输出你对重资产历史事实、capex/DA 结构、默认排程和关键不确定性的理解，再逐项等分析师确认。不要把 `da_facts_latest.json`、完整 YAML schema 或资产明细机械倾倒给用户；完整审计写入 `da_schedule.yaml`。

## 关键纪律(不可妥协)

- **与 A/B 的关系**:本 skill 不写 `核心假设.md`(`核心纪律` A / `核心假设源语言` B 管 `核心假设.md` 写作,不直接适用);产物是 `da_schedule.yaml`,纪律见本执行细则 + `CLAUDE.md` 开发总原则 + 事实↔假设分离。
- **先押再问拍板才落盘**:控制器先押(da_facts + 公司判断 → 推荐选型 + 预测值 + 理由 + 来源),再问用户"你认吗"。用户拍板每一项后才写 `Agent\da_schedule.yaml`。**禁止未经拍板就落盘**。
- **排程讨论会口吻**:先给一页 memo:历史 capex/DA 基线、存量折旧、扩张 capex、转固时滞、终值 capex/DA、存量净增率 g 的建议。每项只问一个自然问题,如"这个 capex 排程你认吗?认了我写入 schedule,再看转固。"
- **事实↔假设分离**:`da_facts.json`(事实,LLM 扒,只填表不推算,抽不到留 null 不补零)vs `da_schedule.yaml`(假设,商议后落盘)。两层不混。
- **产物落 `companies\{公司}\Agent\da_schedule.yaml`**(用 `da_schedule_path`)。`enabled: true` 才被 `src.forecast` 消费；一旦 `enabled: true`，`da_roll` 失败、未执行或被忽略都必须阻断 official forecast，**不得自动回退轻资产路径**。只有 `enabled: false` 或文件缺失时，才允许使用轻资产默认路径。若分析师明确要临时忽略 DA，只能输出/运行 `reference·DA未生效`，不得覆盖正式 DCF。
- **落盘后提示用户重跑** `py -m src.forecast --ticker {代码}`:`forecast.py` 的 `_maybe_roll_da_series` 会加载 da_schedule → `roll_da_series` 产 da_series → gpm→ex-dep 覆盖 → 注入 forecast_params → `calc.py` 重资产分支(BS 的 `fix_assets`/`cip` 从 da_series、CF/FCFF 的 capex/da 从 da_series)。`DaAlignError`(base_year ≠ defaults.base_period)硬抛；其他 `da_roll` 异常在 `enabled: true` 下同样阻断 official forecast，只能出 `reference·DA未生效`，不能 warning 后静默回退轻资产。
- **通用性第一原则**:不写死任何公司特征(行名/业务线数量/年限/单位/拆分层级)。见 `CLAUDE.md` 开发总原则。换任何重资产公司只要年报披露了 DA 附注就能跑。
- **不读 PDF**:只信任已经翻译进 `.md` 的年报内容(平移 /comp、/ka 纪律)。
- **三类摊销(无形/使用权/长摊)不进 da_schedule**,仍由 yaml1/defaults 管。`da_roll` 只产 `ppe_depreciation`(PP&E 折旧),总 DA 装配在 `calc.py` 一处显式做。

## CLI

```bash
/da 新乳业
/da 002946
/da 002946.SZ
```

## 退出码

- `0`:`Agent\da_schedule.yaml` 落盘成功(主产物已落盘,enabled 状态由商议结果决定)。
- `2`:输入无法解析为唯一公司目录。
- `3`:缺少 `公司判断和最新观点.md` 或同权重定调材料准备失败。
- `1`:执行细则流程异常或 IO 错误(da_schedule 未生成)。
