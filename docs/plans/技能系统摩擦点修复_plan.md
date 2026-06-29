# 技能系统摩擦点修复 plan

> 来源：对 12 个启动器（`.claude/skills/*/SKILL.md`）+ 9 个动态细则（`skills/*_skill_v*.md`）的 source-of-truth 架构审查。
> 根因诊断：**真源已存在（`退出码与对齐契约.md`、`knobs块契约.md` 等契约文档齐全），但 skill 习惯性本地重抄同一条规则、措辞微差、互不引用，执行者每次都要做"这两处是不是一回事"的对齐。** 本 plan 的主轴就是"抽到契约单一真源、skill 只回指不重抄"。
> 执行原则：surgical changes——每条改动都能追溯到本 plan 的某一项；不重构没坏的逻辑、不"顺手"改风格。

---

## P1 硬冲突（会直接卡住或误判，最先改）

### P1-1 拆 comp exit 2 双义 + annual-update staleness 收敛

- **问题**：`comp/SKILL.md` 自己的退出码表把 exit 2 写成"公司目录解析失败"，而 `:25` 又把"读 `assumption_staleness` 退出码 2 = 年份门禁 stale"当 /comp 停止信号——同一启动器内 exit 2 既是自身语义又是子进程语义。`docs/退出码与对齐契约.md:15` 已记录这个 OR 混用但没强制拆。后果：用户被 /comp exit 2 弹去 /annual-update，其第 3 步 fetcher 又 exit 2 弹去 /init，三命令乒乓球。
- **涉及文件**：
  - `.claude/skills/comp/SKILL.md`（拆码 + 退出码段改回指）
  - `.claude/skills/annual-update/SKILL.md`（补 staleness 收敛判据 + 退出码段改回指）
  - `.claude/skills/init/SKILL.md`、`da/SKILL.md`（退出码段改回指，保留各自特有项）
- **改法**：
  1. comp 启动器：把"assumption_staleness 退出码 2"明确写成"子进程 `assumption_staleness` 返回 2（stale）"，与本启动器自身 exit 2（公司目录解析失败）区分；在退出码表加注"子进程码见 `退出码与对齐契约.md`"。
  2. annual-update：补一句"annual-update 完成后，重跑 `assumption_staleness` 应返回 0；若仍返回 2，说明 H→A 滚轴未覆盖预测起点，需检查显式期/衰减期是否也要重定"。
  3. 各 SKILL.md 退出码段落：改成"完整退出码见 `docs/退出码与对齐契约.md`，此处只列本启动器特有项"，删去与契约文档重复的行。
- **验证**：`退出码与对齐契约.md` 表格与各 SKILL.md 不再互相矛盾；comp 自身 exit 2 与 assumption_staleness exit 2 在文字上可区分。

### P1-2 /adj quick/incremental 合并单一决策树

- **问题**：`adj/SKILL.md:38-39` 用关键词黑名单（命中"增量/读材料/ADJ材料/新信息/边际信息"才 incremental），`核心假设调整器_v1.md:34-36` 用语义例句（"竞争格局变了"→incremental 但不含关键词）。两套判据互不兼容、会误命中。
- **涉及文件**：`.claude/skills/adj/SKILL.md`、`skills/核心假设调整器_skill_v1.md`
- **改法**：launcher 改成单一决策树：
  1. 请求能否语义映射到已有 knobs 的 `values[i]`？
     - 能 + 不碰结构/horizon/fade → quick
     - 不能，或带新业务理由/新材料/结构变化 → incremental
  2. 关键词清单降级为"提示信号"而非判据。
  - v1 删掉与 launcher 重复的判据段落，只留示例。
- **验证**：launcher 与 v1 不再有互斥判据；"竞争格局变了，销售费用率降 0.5pct"按新决策树唯一走 incremental。

### P1-3 /da 补轻资产判定与退出口 + exit 0 细分

- **问题**：`da/SKILL.md:12` 说轻资产不该用，但第三动作（`:39-46`）无任何轻资产检查点；"轻资产"无量化标准、无主体、无退出口；`:84` 规定 enabled:true 后不得自动回退轻资产 → 误判即阻断 official DCF。exit 0 语义过强（落盘成功但 enabled 可能 false）。
- **涉及文件**：`.claude/skills/da/SKILL.md`、`skills/da_折旧摊销排程_skill_v1.md`
- **改法**：
  1. 在第三动作前加显式轻资产判定步骤：量化锚点（capex/revenue 历史均值 < 阈值 且 固定资产/总资产 < 阈值 → 提示可能不需要 /da），由 launcher 判、需用户确认。
  2. 给退出口：判为轻资产时提示"建议直接用 defaults 跑 forecast"并停（不落盘 enabled:false 的 schedule）。
  3. exit 0 细分：exit 0 = 落盘且 enabled=true；落盘但 enabled=false 单列语义（或 exit 4），并在汇报语加"enabled=false 不代表重资产 DCF 已生效"。
- **验证**：da SKILL 流程含可执行的轻资产判定步骤；exit 0 不再承诺 enabled=false 的"成功"。

### P1-4 主动覆盖改标记制（不读心）

- **问题**：`yaml1compiler_v5.md:167,547` 要求 audit 单独回读"主动覆盖线"，但判定靠执行者猜分析师是不是"故意不照搬券商"。
- **涉及文件**：`skills/yaml1compiler_v5.md`、`skills/核心假设编辑器_skill_v1.md`
- **改法**：
  1. compiler 把"主动覆盖"判定从"猜意图"改成"认标记"：要求 /ka 在源文对主动覆盖线打 `[主动覆盖]` 标，compiler 只对标线单独回读。
  2. 编辑器 runbook 在"写盘前收口"补一条：主动覆盖线须在源文打标。
- **验证**：compiler 不再要求执行者判定意图；源文无标线不进主动覆盖回读表。

---

## P2 重抄漂移收敛到单一真源

### P2-1 新建 `docs/旋钮白名单与结构判定.md`（单一真源）

- **问题**：quick 旋钮白名单在 `核心假设调整器_v1:79-87` 与 `frontend-edit:98-112` 两份且对不齐（adj 有 `financial_expense` 族、frontend 没有）；quick 禁止清单在 `adj/SKILL.md:70-77` 与 `调整器_v1:88-97` 两份措辞/粒度不同；"结构改动/推翻骨架"在 adj/调整器/年度更新器三处四个叫法。
- **涉及文件**：新建 `docs/旋钮白名单与结构判定.md`；改 `.claude/skills/adj/SKILL.md`、`.claude/skills/frontend-edit/SKILL.md`、`.claude/skills/annual-update/SKILL.md`、`skills/核心假设调整器_skill_v1.md`、`skills/年度更新器_skill_v1.md`
- **改法**：新文档含三张表：
  1. **quick 可拨旋钮白名单**（含 `financial_expense` 族——统一为"可拨"，frontend-edit 映射表补登）。
  2. **quick 禁止清单**（业务语言 + yaml1 path 双列，单一超集）。
  3. **结构改动判定表**（可观测特征 → 处理路径：改 values=quick / 新增删除线或改参数化族或改 horizon/fade=incremental 开骨架门 / thesis 方向反转=弹回 /ka）。
  - 各 skill 删本地副本，改"见 `docs/旋钮白名单与结构判定.md`"。
- **验证**：全库 grep 不到第二份 quick 白名单/禁止清单；financial_expense 族在两个 skill 行为一致。

### P2-2 §6b 门禁收口 + BRKD/LOAD 计数对齐

- **问题**：§6b"三者全无"在 `ka/SKILL.md:139`、`webka/SKILL.md:30`、`webka.py:189` 三处措辞漂移；BRKD 档计数对象不同（KA 目录内 brkd 参考稿算不算）；LOAD 完成性 ka 列 5 条排除、webka 只 2 条。
- **涉及文件**：`skills/核心假设编辑器_skill_v1.md`（门禁定义一次）、`.claude/skills/ka/SKILL.md`、`.claude/skills/webka/SKILL.md`、`src/webka.py`
- **改法**：
  1. 门禁定义只在编辑器 §0 一处；ka §6b 末尾回指。
  2. 显式声明：BRKD 档只认公司根目录 `Agent业务讨论.md`；KA 目录内 `核心假设参考brkd_*.md` 归"KA 目录 markdown"档。
  3. webka.py 的 LOAD 完成性判定补齐到与 ka §6 一致（抬头校验 + 路径排除），或在 webka SKILL 显式声明"webka 门禁是 ka §6 子集，剩余由 /ka 本地把关"。
- **验证**：ka/webka/webka.py 三处门禁措辞一致或显式声明子集关系。

### P2-3 /load 主产物/沙箱路径 + "一字不差"收口

- **问题**：路径与同步纪律在 `load/SKILL.md`、`模型装载器_v3`、`webload/SKILL.md` 三处各写一份；"一字不差"是口令不是机制。
- **涉及文件**：`skills/模型装载器_skill_v3.md`（单一真源）、`.claude/skills/load/SKILL.md`、`.claude/skills/webload/SKILL.md`
- **改法**：路径与同步纪律集中到模型装载器 v3 一处；load/webload SKILL 改回指。明确"脚手架写沙箱、AI 续写改沙箱、定稿后同步到 KA 参考稿区"的单写源方向（措辞用"唯一写源/镜像"替"主/副"）。
- **验证**：三处不再各自重述路径；"一字不差"有明确的单写源 + 同步动作指向。

### P2-4 模型装载器权威顺序去重

- **问题**：`模型装载器_v3:50` 与 `:151` 重复定义权威顺序，措辞不同。
- **涉及文件**：`skills/模型装载器_skill_v3.md`
- **改法**：删 `:151` 重复，改"见 §1 权威顺序"。
- **验证**：文件内权威顺序只定义一次。

### P2-5 会议 memo 交互风格收口到核心纪律 A4

- **问题**：交互风格在 `核心纪律 A4`、`编辑器 §0.1/§3`、`yaml1compiler §9` 三处三种措辞。
- **涉及文件**：`skills/核心纪律_skill_v1.md`（保留）、`skills/核心假设编辑器_skill_v1.md`、`skills/yaml1compiler_v5.md`
- **改法**：风格只在 A4 定义；编辑器 §0.1/§3、compiler §9 删风格描述，改"继承 A4"回指 + 业务特有字段清单。
- **验证**：交互风格定义只一处。

### P2-6 分红率检测收成单一决策表

- **问题**：`编辑器 §0/§6/§10` 三处讲分红率检测，判据层层加码、不统一。
- **涉及文件**：`skills/核心假设编辑器_skill_v1.md`
- **改法**：§6 收成单一决策表（触发条件 → 动作）；§0、§10 改回指。
- **验证**：分红率检测判据只一处。

---

## P3 伪版本管理

### P3-1 "动态加载最新版 skill" 定规则 + 共享骨架写死

- **问题**：`ka/comp/brkd/load` SKILL 写"扫描 `*_skill_v*.md` 取最新版"，但无排序规则；当前每 skill 只一版本，"动态加载"空转；`核心纪律`/`源语言` 自声明是 include 单一真源，却用 v* glob 引用。
- **涉及文件**：`.claude/skills/ka/SKILL.md`、`comp/SKILL.md`、`brkd/SKILL.md`、`load/SKILL.md`、`adj/SKILL.md`、`annual-update/SKILL.md`、`da/SKILL.md`、`frontend-edit/SKILL.md`
- **改法**：
  1. 共享骨架文件（核心纪律、核心假设源语言）一律写死文件名，不用 v* glob。
  2. operation skill（编辑器、compiler、业务预理解器、模型装载器、调整器、年度更新器、da）保留"动态加载最新版"，但显式定义"最新 = 按文件名 `vN` 的 N 做整数比较取最大"。
- **验证**：共享骨架引用无 glob；operation skill 引用含整数排序规则。

---

## P4 命名漂移与杂项

| 编号 | 问题 | 文件 | 改法 |
|---|---|---|---|
| P4-1 | "证据入口" vs "判断材料" 不同义 | `ka/SKILL.md:74`、`编辑器:13` | 统一为"判断材料入口" |
| P4-2 | /load prepare"锁定" vs AI"确认"职责不清 | `load/SKILL.md:67`、`模型装载器_v3:66-77` | 明确 prepare=机器初值、AI=校验可修正、冲突以 AI 手读为准但须报告 |
| P4-3 | comp 输入材料"六份/四份/七份" | `comp/SKILL.md:28`、`yaml1compiler_v5:130` | 删计数，直接给清单 |
| P4-4 | `model_assumption_schema.json` 悬空"交给 /comp" | `编辑器:42` | 删甩锅句或补进 /comp 清单（核验该文件是否仍被使用，若废弃则标注） |
| P4-5 | frontend-edit "前端新增旋钮族须登记" 无归属 | `frontend-edit/SKILL.md:111` | 指向 P2-1 新建文档为登记入口，未登记时降级提示而非报错停死 |
| P4-6 | v19 残留禁令污染当前决策 | `ka/SKILL.md:70`、`编辑器 §0` | 删 v19 禁令；"你不再负责"改正向陈述 |
| P4-7 | perpetual_growth "固定 0.025" vs "与 defaults 保持一致" 潜在冲突 | `yaml1compiler_v5.md:502,504` | 明确优先级：跟随 defaults.yaml `model.terminal_growth`，当前为 0.025 |
| P4-8 | leaf_margin knobs 回声矛盾（A6 必须回声 vs B4 暂不写） | `核心假设源语言:170-171` | 给明确裁决：分线毛利率回声形态（折进父收入线 / 独立条目） |
| P4-9 | fade profile 四档纯定性、需读心 | `编辑器:150-161` | 每档加粗量化锚点（收入 CAGR 区间等），"建议阈值可被分析师推翻" |
| P4-10 | to_year 歧义四步第(2)步"取自洽解"无 tie-break | `yaml1compiler_v5.md:489` | 加默认偏向规则（更短 fade / 更低 target，偏保守） |
| P4-11 | yaml1compiler §0 约 100 行认知铺垫信噪比低 | `yaml1compiler_v5.md:5-103` | 压缩到 20-30 行，只留三条铁律 + 举旗机制，比喻移附录/删 |
| P4-12 | webka "不必要读强制碰到再速查.md" 命名误导 | `webka/SKILL.md` + `src/webka.py` | 改名 `速查参考.md` |
| P4-13 | webload "极简"措辞 + 历史负面清单残留 | `webload/SKILL.md:67` | 删"不打包单独阅读件"历史遗留；"极简"改"单文件合并 + allowed_materials 目录" |
| P4-14 | webka 不写 manifest / webload 写，哲学相反未说明 | `webka/SKILL.md:16`、`webload/SKILL.md:49` | webload 补"manifest 供本地复用，网页端不读" |
| P4-15 | /da 第二阶段"先押再问/拍板才落盘"launcher 与 v1 重复 | `da/SKILL.md:80-81`、`da_v1:76-91` | launcher 改"见 v1 §4.1-4.3" |
| P4-16 | /annual-update 按需扩展写两遍 + 滚后时间轴确认门归位错 | `annual-update/SKILL.md:58,107,132-144` | 第1步识别动作删，只留"按需扩展"专节；确认门归到第2步末尾（与 v1 对齐） |
| P4-17 | ka §3b 复述人工筛选门（与自身 line 14 声明矛盾） | `ka/SKILL.md:72-80` | 删复述，改回指编辑器 §0 / 核心纪律 A0.1 |
| P4-18 | cli 风格不统一（model_load 子命令 vs 其他无） | `load/SKILL.md:61` | 轻量：在 load SKILL 注明"model_load 用 prepare 子命令"，不改代码 |

---

## 执行顺序与验证总则

1. **先建真源**（P2-1 新文档、P2-2/P2-3/P2-5/P2-6 收口点）→ 再改 skill 回指 → 最后清杂项（P4）。
2. P1 硬冲突与建真源并行无依赖，可同批。
3. 每改一个文件前先 Read（编辑器要求 + 确保行号未漂移）。
4. 改完跑 `py -m py_compile` 验 `src/webka.py`（若改了）；grep 验证"第二份副本已消失"。
5. 全部完成后记 `docs/CHANGELOG.md` 一行；`数据流水线.md` 本次不动（不涉及取数/clean/forecast 代码）。

## 不做（边界）

- 不改 `src/` 的实际取数/clean/forecast/da_roll 逻辑（仅 `webka.py` 门禁判定对齐可能触及）。
- 不重写 skill 的业务规则，只去重、收口、补判据、拆歧义。
- 不删任何历史/deprecatedlogs 内容（v19 禁令删除是指删 SKILL 里的残留指令，不动 deprecatedlogs 文件本身）。

## 执行偏差（实施时记录）

- **P3-1 骨架钉死撤销**：实施时发现 `tests/test_*_skill_docs.py` 明确断言 `核心纪律_skill_v*.md` glob 存在于各 launcher/runbook，且 `frontend-edit` 显式声明"勿钉死 v1"——项目既有约定是"骨架用 glob 不钉死"。遂撤销骨架钉死、回退 glob；仅 operation skill（编辑器/compiler/业务预理解器/模型装载器/调整器/年度更新器/da排程）的"动态加载最新版"加"`vN` 整数比较取最大"排序规则（修 v10<v3 字符串排序坑，这是 P3-1 的真修复）。骨架 glob 保持原状。
- **P4-11 缓做**：yaml1compiler §0 约 100 行认知铺垫，各小节（§0.4 举旗/§0.5 A·B 类/§0.5a 信息保全闸/§0.6 不算账）被全文 `§0.X` 交叉引用，全文重写有断链风险。本次仅做其他 P4 杂项，§0 压缩留作独立专项。
- **测试同步**：本次 doc 结构改动同步更新 `test_*_skill_docs.py` 断言钉新结构（非削弱守卫，是跟随有意改进）。`test_calc_yearly[600887.SH]` 预存在失败，由工作树里先前会话的 `src/init.py`/`src/core_metrics_overview.py` 未提交改动导致，与本次 skill 重构无关，未触碰。

