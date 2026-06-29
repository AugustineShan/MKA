# /ka 读取清单与流程清单

> **本文是导航索引，不是规则真源。** 规则仍以 `skills/核心纪律_skill_v*.md`（A）、`skills/核心假设源语言_skill_v1.md`（B）、`docs/knobs块契约.md`、`skills/核心假设编辑器_skill_v1.md`（裁决 runbook）、`.claude/skills/ka/SKILL.md`（启动器）为准。本文只把「按什么顺序做什么、每步读什么」摆在一处，不复述规则本身。

`/ka` 只做一件事：把业务层材料裁决成一份新的正式 `核心假设.md`。它不是旧稿 modify 工具。范围默认收窄为**利润表 + 业务层盈利模型裁决器**；细节见编辑器 runbook §0 与源语言 B0.1。

**主导方向**：拿 /brkd、/load、Alphapai 产物和分析师裁决预测，同时忠实收集与预测有关的历史防丢数——预测会变，历史是锚（见编辑器 runbook 核心指导）。上游 brkd/load 的首要任务是忠实抓业务拆分+历史+收纳数据（即便不参与计算），那是 /ka 裁决的弹药。

---

## 一、流程清单（按执行顺序）

启动器（SKILL.md）管机械，编辑器 runbook 管裁决。下表左列是步骤，右列是进入哪段 runbook。

| # | 步骤 | 做什么 / 跑什么 | 声明处 |
|---|---|---|---|
| 0 | 加载真源 | 先加载 4 份规则（见下文必读·规则层） | SKILL.md §0 |
| 1 | 解析公司目录 | 从 `$ARGUMENTS` 定位 `companies\{公司}`（精确/代码/公司名匹配，多命中询问） | SKILL.md §1 |
| 2 | 已有正式稿门禁 | Glob `companies\{公司}\核心假设*.md`；有旧稿且用户没明说「重建」→ 停止，分流到 `/adj`、`/frontend-edit`、`/annual-update` | SKILL.md §2 |
| 3 | 加载编辑器 runbook | 读 `核心假设编辑器_skill_v*.md`，裁决流程在它的 §2-§10 | SKILL.md §3 |
| 4 | 人工筛选门 + markdown 化同权重判断材料 | `py -m src.ka_prepare "{公司}"`，只处理人工筛选入口里的 `公司判断和最新观点.md` + `重要文件/` 顶层材料 + 最高权重材料文件夹顶层；`markdown存储区\` 是 cache，不代表其他 cache 可读 | SKILL.md §3b/§4 |
| 5 | 读 BRKD 产物 | 读 `Agent业务讨论.md`（KA 参考稿区另有 `核心假设参考brkd_*.md` 须声明 draft/reference，仅作候选） | SKILL.md §5 |
| 6 | 读 LOAD 产物 + 门禁 | 扫 KA 参考稿区 `核心假设参考load_*.md`；空脚手架/「待模型装载器补全」/无 knobs 自报/非 load-vintage/WEBCLAUDE 副本都不算门禁通过；多个取最新 | SKILL.md §6 |
| 7 | 读 KA 目录 markdown + 门禁 | 扫 KA 目录顶层全部 `*.md`；**BRKD/已完成 LOAD/KA 目录任一 markdown 三者至少一，否则停止**；`核心假设参考*.md` 按候选稿裁决，其他 markdown 按信息指引读 | SKILL.md §6b |
| 8 | 进入编辑器裁决流程 | 见下方「裁决流程」子表 | 编辑器 §1-§10 |
| 9 | 落盘 | 重建且已有旧稿→先 `py scripts/ka_archive.py "<旧稿路径>"`；再写 `companies\{公司}\{公司名}-{今日YYYYMMDD}-核心假设.md`（悬项写 `…核心假设参考.md`） | SKILL.md §7 / 编辑器 §10 |

### 裁决流程（编辑器 runbook，§1-§10）

每段都「先押判断 → 等分析师拍板 → 拍板才落盘」，按语义区块停，不连写。

| 段 | 做什么 | 编辑器 § |
|---|---|---|
| 输入权重 + defaults 审计 | 按权重排冲突（同权重判断材料 > BRKD > LOAD > reference > /init > 年报）；**必读 `Agent/defaults.yaml`**，摘 `base_period`、关键参数 `value/source/method`、顶层 `review_flags` | §1 / §1.1 |
| 锁时间轴四数 | 历史至哪年 / 显式期 / 衰减期 + `target_growth` / 永续点；四数至少落三处 | §2 |
| 自动 fade profile | 自动给 linear fade（mature/stable_brand/long_runway/cycle_repair），用户只拍板 | §2.1 |
| 开场 overview | 摆门禁来源、缺口、三方时间边界、建议骨架；**停，等认可时间轴+骨架** | §3 |
| 接缝总账 | 入模/收纳/缺口/丢弃四桶；分红率单列去处；旧稿只对照不逐行 base | §4 |
| 骨架门 | 收入拆分/科目/family/毛利耦合；family 必须落在源语言 §B4 集合内；**停，等认可** | §5 |
| 数值门 | 收入→毛利→费用→below-OP/税/少数→分红率强制检测→可选 BS/CF 人工覆盖→中期/terminal，每段押→拍板→落盘 | §6 |
| 年报查证 | 拿不准时查对应附注（税率/below-OP/费用归类/少数股东/口径变更） | §7 |
| 防静默 passthrough | 冲突按 A2 裁决、格式按 B7 写；LOAD/BRKD knobs 不得整块静默变 official | §8 |
| 收口 + 落盘 | 接缝/骨架/范围/分红率/历史保全/时间轴/knobs 同源全核对 | §9 / §10 |

---

## 二、读取清单

### 必读·规则层（先加载，先于任何材料）

| 文件 | 作用 |
|---|---|
| `skills/核心纪律_skill_v*.md` | A0-A7 横切纪律 |
| `skills/核心假设源语言_skill_v1.md` | B0-B10 块语法 + §B4 family 三硬规则 |
| `docs/核心假设源语言语法规范.md` | 标准块头、候选稿清单、reference 裁决回执、受控词表 |
| `docs/knobs块契约.md` | 末尾 ` ```knobs` 机器自报清单真源 |
| `skills/核心假设编辑器_skill_v1.md` | 裁决流程 runbook（§1-§10） |

### 必读·材料层（裁决输入，每次都读）

人工筛选门：以下入口之外的 markdown cache、`WEBCLAUDE` 包、`Agent/Load` 沙箱副本、临时转换件默认不读，除非用户明确说“这份材料进入本轮判断”。KA 目录 `companies\{公司}\Skills素材包\KA（ALPHAPAI拆出来的东西放在这里）\` 是例外中的明确入口：顶层所有 `*.md` 都读，非 `核心假设参考*.md` 按信息指引处理。

| 文件 | 角色 |
|---|---|
| `companies\{公司}\公司判断和最新观点.md` | **同权重判断材料默认项**（分析师当前 thesis、口径、偏好）；经 ka_prepare markdown 化后读存储区 |
| `companies\{公司}\重要文件\` 顶层材料 | 与公司判断同权重，常放最重要、最新的会议纪要；同样只读 `markdown存储区\` + manifest，不读 raw |
| `…\Skills素材包\最高权重材料-放Agent最应对齐的材料\` 顶层材料 | 同权重判断材料其余项；文件夹名是历史目录名；同样只读 `markdown存储区\` + manifest，不读 raw |
| `Agent/defaults.yaml` | 机器平推底座 + 目标命名空间；§1.1 必须摘 `base_period`/关键参数 `value/source/method`/`review_flags`，分红率强制检测的核对对象 |

### 门禁材料（业务骨架来源，三者至少一，否则停止）

| 文件 | 角色 | 输入权重 |
|---|---|---|
| `companies\{公司}\Agent业务讨论.md` | BRKD 产物，当前业务结构与利润表讨论第一起点 | #2 |
| KA 参考稿区 `核心假设参考load_*.md` | LOAD 产物，旧模型量价原子/分线历史/公式族，标 `load-vintage`；多个取最新 | #3 |
| KA 目录顶层 `*.md`（含 `核心假设参考*.md` 与其他 markdown） | reference 候选或信息指引。`核心假设参考*.md`/reference 状态按候选稿裁决；其他 markdown 不要求 `待 /ka 裁决清单`，按信息指引读入 overview 和接缝总账 | #4 |

> 门禁底线（SKILL.md §6b）：同权重判断材料、旧正式稿、`公司判断和最新观点.md` **不计入此门禁**——它们是裁决材料或旧稿对照，不是业务骨架来源。

### 重要参考（条件性）

| 文件 | 何时读 |
|---|---|
| `companies\{公司}\核心假设*.md`（旧正式稿） | 仅重建时，收口对照 + 防静默丢信息；不逐行 base |

### 速查（问题触发才查，不强制通读）

| 文件 | 查什么 |
|---|---|
| `Agent/core_metrics_overview.{md,json,csv}` | 利润表事实（收入/毛利率/三费率/有效税率/少数股东比） |
| `Agent/OfficialBreakdowns/business_revenue_breakdown*.csv\|jsonl` | 官方业务拆分口径；只证历史口径，不给预测。副拆分毛利率由 /comp 自动提取，KA 不手写 |
| `Agent/financial_expense.yaml` | 财务费用附注，默认只收纳/分流 |
| `Agent/data.db`（`clean_annual`/`clean_quarterly`） | 结构化事实兜底 |
| `公告/年报/*.md` | 年报正文兜底，X 光片不是主材料，按需查附注 |
| `docs/yaml1算法模板契约.md` | cleaner 折叠/unit_factor 等 yaml1 侧细节；**/comp 读，/ka 一般不加载** |

---

## 三、机械脚本

| 命令 | 时机 |
|---|---|
| `py -m src.ka_prepare "{公司}"` | §4，幂等 markdown 化同权重判断材料（公司判断 + 重要文件 + 最高权重材料文件夹） |
| `py scripts/ka_archive.py "<旧稿完整路径>"` | 重建且根目录已有旧正式稿时，落盘前先归档（铁律 1，禁止原地覆盖） |

---

## 四、停止条件速览

- **§2 门禁**：根目录已有正式稿且未明说「重建」→ 停，分流到 `/adj`、`/frontend-edit`、`/annual-update`。
- **§6b 门禁**：BRKD 产物 / 已完成 LOAD 产物 / KA 目录顶层 markdown **三者都没有**→ 停，提示先跑 `/brkd`、补 `/load` 或把要给 `/ka` 看的 markdown 放入 KA 目录。
- **编辑器 §0**：只有同权重判断材料或旧正式稿、没有 BRKD、完成 LOAD 或 KA 目录 markdown → 停，不凭空生成业务骨架；若只有信息指引但缺业务骨架，先在 overview 标缺口并停。
