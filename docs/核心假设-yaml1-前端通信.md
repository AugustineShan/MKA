# 核心假设.md ↔ yaml1 ↔ 前端 通信全链路

> **阅读对象**：任何需要改动「核心假设.md 格式」「yaml1 字段/路径」「workbench 旋钮渲染/预览逻辑」「前端编辑回写」其中任何一环的人。
>
> **强制阅读规则**（已写入 `CLAUDE.md`）：上述四类变更**必须先读本文**，再读具体契约；本文只讲结构和流程，不重复具体语法——具体语法看本文末尾「分层文档」表格里的对应文档。

---

## 0. 一句话心智模型

```
核心假设.md  ──[/comp]──▶  yaml1_*.yaml  ──[forecast]──▶  Agent/forecast/
  (canonical，                (派生缓存，                   (DCF 结果)
   人话权威层)                 机器可读)
       ▲                           ▲
       │                           │   ← 前端只读 yaml1，不直接读 md
       └──[/frontend-edit]─────────┘   ← 回写时同时写 md 正文+knobs块 和 yaml1
```

**唯一铁律**：`核心假设.md` 是 canonical（唯一事实源），`yaml1` 是它的**派生缓存**。任何时候三处（md 正文 / md knobs 块 / yaml1）冲突，**md 赢**，停止并回到 `/comp` 重编译。

---

## 1. 正向链路：md → yaml1（/comp）

### 1.1 md 里有什么

`核心假设.md` 有两层内容：

| 层 | 内容 | 作用 |
|---|---|---|
| **正文预测行** | 人话叙述 + 逐年数（如 `销量 yoy: 2025 +8%…`） | 人可读，canonical 意图 |
| **末尾 ` ```knobs ` 块** | 机器自报清单，每条 `{anchor, sub, family, unit, values:[...]}` | md 与 yaml1 之间的**桥**，fidelity_check 的校验基准 |

knobs 块是 md **内部的机器层**，不是 yaml1——它描述「我声明了哪些旋钮、值是什么」，供编译器和校验器读取。具体语法见 `docs/knobs块契约.md`。

正文数值是 knobs 块的**派生回显**（frontend-edit 第 12 步回填），不是独立事实源。人只需维护措辞和判断；数字由工具写回。

### 1.2 /comp 做什么

/comp 是唯一翻译器（`skills/comp/SKILL.md`）。执行顺序：

1. 年份门禁（`src.assumption_staleness`，确认 clean_annual 未超过预测起点）
2. 读 `核心假设.md`（语义层：判断/历史/旋钮/时间轴）
3. 读 `Agent/defaults.yaml`（**目标命名空间**，不是输入假设）
4. 通过 Semantic IR 盘点（`docs/核心假设翻译IR契约.md`）将 md 内容分 A 类（进 DCF）/ B 类（进 stash/history/display）/ 歧义（进 unaligned）
5. 写 `Agent/yaml1_公司名_YYYYMMDD.yaml`
6. 跑确定性双射闸门（见 §3.1）
7. 跑正式 DCF（`src.forecast`）

**yaml1 不是新建的空白文件**：它的每条路径都落在 `defaults.yaml` 已有路径上，覆盖其中需要人工判断的部分。没有被覆盖的路径继续由 defaults 的机器平推值生效。

---

## 2. 前端读取：yaml1 → 工作台表格

### 2.1 初始加载

```
GET /api/companies/{company_id}
```

后端（`src/workbench.py`）把 yaml1 解析成：

| 字段 | 含义 | 来源 |
|---|---|---|
| `yaml1_revenue_view` | 分线收入视图（按 family 折叠，yoy 锚定到 clean_annual 基年总额） | `_yaml1_revenue_view_from_data()` |
| `editable_assumptions` | 可编辑旋钮列表，每条带 JSON Pointer（如 `/income/gpm/values/0`） | `_editable_assumptions()` |
| `yaml1_assumptions_view` | 关键假设分组（毛利率/费用率/税率/少数股东…） | `_yaml1_assumptions_view()` |
| `yaml1_business_facts_view` | 业务拆分历史 + 毛利率（Business Fact Matrix） | `build_business_fact_view()` |
| `yaml1_display_contract` | 前端布局契约（role/placement/dimension） | `_yaml1_display_contract()` |

**前端「① Model table 收入拆分 + 关键假设」由这两个数据源渲染**：
- 收入拆分行 → `yaml1_revenue_view.segments`（`buildRevenueGroups()`）
- 关键假设行 → `yaml1_assumptions_view`（`buildAssumptionsGroups()`）
- 每个 cell 带一个 JSON Pointer，精确指向 yaml1 数据结构里的具体位置

### 2.2 分线收入引擎（唯一引擎）

分线收入的 per-family 数学（`growth`/`abs`/`vol_price`/`factor_product`/`formula`）**统一在 `src/revenue_fold.py`**：

```
src/revenue_fold.py
  ├── project_leaf()        # 单 leaf 折叠（全 family，严格报错不静默）
  ├── iter_leaves()         # 遍历 decomposition 树
  ├── REVENUE_FAMILIES      # 合法族集（唯一真源，fidelity_check 和 lint 都 import 这里）
  └── Yaml1CleanError       # 引擎异常（cleaner 再导出）
```

`yaml1_cleaner.fold_revenue`（forecast）和 `workbench._yaml1_revenue_view_from_data`（前端预览）都调这个引擎。两者对 clean_annual 基年实际总额做同样的锚定——保证**预览总额/同比 == DCF 实际跑的数**。

> ⚠️ **如果你新增/修改 revenue_family**：只改 `REVENUE_FAMILIES`，其他地方（fidelity_check/ka_assumption_lint/workbench）自动同步。**不要**在其他文件重复定义 family 集合。

---

## 3. 内存试算：用户改旋钮（不落盘）

### 3.1 触发流程

```
用户改一个 cell 值
  ↓
前端 draftValues[pointer] = newValue
  ↓
patches = buildAssumptionPatches()
  [{pointer:"/income/gpm/values/0", old_value:0.35, new_value:0.38}, ...]
  ↓
POST /api/companies/{id}/assumption-preview { patches }
  ↓
后端：
  1. _apply_assumption_patches()    ← 验证 old_value 仍匹配（防冲突）
  2. 把 patches 套到内存中的 yaml1 副本
  3. _yaml1_revenue_view_from_data() ← 调 revenue_fold 重算分线收入
  4. （可选）跑完整 forecast 三表
  ↓
Response: { revenue_view, result_rows, errors }
  ↓
前端用 preview.revenue_view 覆盖显示（分线/总收入/同比联动）
```

**重要**：`assumption-preview` **不写任何文件**。它是纯内存操作——改的是 yaml1 的内存副本，不是磁盘上的 `yaml1_*.yaml`，更不会碰 `核心假设.md`。

### 3.2 白名单范围

只有出现在 `editable_assumptions` 里的旋钮才能被 patch。生成规则在 `_editable_top_level_value_knobs` / `_editable_revenue_driver_knobs` / `_editable_terminal_knobs`。

哪些旋钮在白名单内、哪些属于结构性改动：`docs/旋钮白名单与结构判定.md`（唯一真源）。

---

## 4. 回写链路：确认 → /frontend-edit → 落盘

### 4.1 生成 prompt

用户确认试算结果后：

```
POST /api/companies/{id}/assumption-brief { patches, preview_summary }
  ↓
后端 _format_frontend_edit_prompt() 拼出：

/frontend-edit 进入前端编辑模式，基于当前核心假设.md 更新 {company} 的假设并更新DCF

关键纪律：...

核心假设路径：companies/{公司}/{公司名}-{YYYYMMDD}-核心假设.md
当前 yaml1 路径：companies/{公司}/Agent/yaml1_{公司名}_{YYYYMMDD}.yaml

前端试算变更：
- {label} ({path}) {year}: {old} -> {new}
  (例: 整体毛利率 (income.gpm) 2025: 0.35 -> 0.38)
```

注意：**prompt 里不带 unit**。`/frontend-edit` 自己从 knobs 块的 `unit` 字段读单位，然后调 `src/unit_convert.py` 做换算（见 §5）。

### 4.2 /frontend-edit 做什么

`/frontend-edit` skill（`skills/frontend-edit/SKILL.md`）是手术刀，把 prompt 里的 diff 安全落盘：

1. 验证 `old_value` 与当前 yaml1 / md knobs 一致（防基于过期状态）
2. 归档旧 `核心假设.md`（铁律 1，先 `py scripts/ka_archive.py`）
3. 写今日新稿 `{公司名}-{今日YYYYMMDD}-核心假设.md`
4. **改 md knobs 块**：对应 `values[i]` 替换为新值（百分数，if pct）
5. **改 md 正文预测行**：替换对应年份数值（正文数值是 knobs 值的派生回显，必须保持一致）
6. **patch yaml1**：定点改对应 `values[i]`（小数）
7. 跑 `yaml1_fidelity_check`（确定性三源双射闸，BLOCK 则停止）
8. 跑 `src.forecast`，回填派生回显（总收入/yoy/归母/fade 路径）

**不会发生**：
- 不读投研材料
- 不调 compiler（旋钮值小改直接 patch，不走 `/comp`）
- 不改历史段

---

## 5. 三处同源与单位约定

### 5.1 三处同源

同一个旋钮值住在三处，必须保持一致：

| 处 | 文件/位置 | 单位（pct 族） |
|---|---|---|
| md 正文预测行 | 例：`销量 yoy: 2025 +8%` | 百分数（8） |
| md knobs 块 `values[i]` | 例：`values: [8, 5, 5]` | 百分数（8） |
| yaml1 对应路径 `values[i]` | 例：`values: [0.08, 0.05, 0.05]` | 小数（0.08） |

**前端 prompt 的 `new_value`** 用小数（0.38），和 yaml1 同单位。`/frontend-edit` 接到 prompt 后：
- 写 yaml1：直接用（0.38）
- 写 md knobs 块：×100 → 38（百分数）

换算唯一真源：`src/unit_convert.py`（`to_decimal` / `to_md_display`）。**任何地方需要 pct↔小数换算，都调这个，不要手抄 `×100` 或 `/100`**。

### 5.2 双射校验

`yaml1_fidelity_check.py` 是 `/comp` 和 `/frontend-edit` **共用的 BLOCKING 闸门**：

```bash
py -m src.yaml1_fidelity_check "<yaml1>" "Agent/defaults.yaml" "<核心假设.md>"
# exit 0 = PASS，exit 1 = BLOCK（md↔knobs↔yaml1 双射失败）
```

BLOCK → md 赢 → 回 `/comp` 重编译，不得继续 patch yaml1 去凑一致。

详细三道闸（A 结构 / B 路径+符号 / C 值双射）：`docs/yaml1忠实度校验.md`。

---

## 6. 什么情况走哪条链路

```
想改预测假设？
  ├── 改的是白名单里的旋钮值（整体毛利率/费用率/税率/revenue yoy 等）？
  │   ├── 已经在前端试算，要落盘 → /frontend-edit（由前端生成 prompt）
  │   └── 直接用 CLI 改 → /adj quick
  │
  ├── 新增/删除业务线、改 family、改时间轴长度、改 terminal 结构？
  │   → 结构性改动，必须走 /adj incremental 或 /ka 重建 + /comp 重编译
  │   → 前端不支持这类改动（白名单外）
  │
  └── 年报/真实数据滚动（base_year 推进，预测起点变化）？
      → /annual-update
```

---

## 7. 修改这套系统时的必读矩阵

| 你要改什么 | 必读（本文之外） | 影响哪些地方 |
|---|---|---|
| knobs 块新增字段/语法 | `docs/knobs块契约.md` | fidelity_check、ka_assumption_lint、frontend-edit、comp |
| 新增 revenue_family | `src/revenue_fold.py` 改 `REVENUE_FAMILIES`，仅此一处 | fidelity_check 和 ka_assumption_lint 自动同步（import）；workbench 自动支持 |
| yaml1 新增顶层路径 | `docs/旋钮白名单与结构判定.md` §一（登记）；`docs/yaml1算法模板契约.md` | /comp compiler、/frontend-edit 白名单闸门、workbench `_editable_*` 函数 |
| pct↔小数换算方向 | `src/unit_convert.py`，唯一真源，改这里 | fidelity_check（调它），frontend-edit skill |
| 前端旋钮渲染（新增可编辑行） | `src/workbench.py` `_editable_*` 函数族 | assumption-preview、assumption-brief API |
| 前端展示布局（role/placement） | `docs/yaml1前端展示契约.md` | workbench `_yaml1_display_contract()`；comp 必须生成 display 字段 |
| 收入折叠数学 | `src/revenue_fold.py` `project_leaf()`，唯一真源 | yaml1_cleaner.fold_revenue（forecast）和 workbench 预览**共用**，改一次全生效 |
| 三源校验规则 | `docs/yaml1忠实度校验.md` | fidelity_check、/comp 第 6 步、/frontend-edit 第 9d 步 |

---

## 8. 分层文档导航

本文是**结构和流程总图**，不重复具体语法。具体规则在这里：

| 层次 | 文档 | 内容 |
|---|---|---|
| md 语法 | `docs/核心假设源语言语法规范.md` | 块头/段头/历史/预测/收纳/terminal 格式 |
| knobs 块语法 | `docs/knobs块契约.md` | anchor/sub/family/unit/values 结构，horizon，terminal 段 |
| 编译规则 | `docs/yaml1算法模板契约.md` | cleaner 支持的 family 模板，fold/expand/resolve 算法 |
| 翻译中间账 | `docs/核心假设翻译IR契约.md` | Semantic IR A/B 类分流，decision 四种出路 |
| 双射校验 | `docs/yaml1忠实度校验.md` | 三道闸 A/B/C，block-diff，符号门 |
| 前端布局 | `docs/yaml1前端展示契约.md` | display 字段，role/placement/dimension，B 类去向 |
| 旋钮白名单 | `docs/旋钮白名单与结构判定.md` | /adj quick 和 /frontend-edit 可操作范围 |
| 单位换算 | `src/unit_convert.py` | to_decimal / to_md_display |
| 收入引擎 | `src/revenue_fold.py` | project_leaf，REVENUE_FAMILIES，iter_leaves |
| 工作台 API | `src/workbench.py` | assumption-preview / assumption-brief 路由及 schema |
| 技能说明书 | `skills/comp/SKILL.md` | /comp 执行步骤，年份门禁，audit 报告 |
| 技能说明书 | `skills/frontend-edit/SKILL.md` | /frontend-edit 13 步，patch 分流，fade 合理性 gate |
| 技能说明书 | `skills/ka/SKILL.md` | /ka 启动门，材料层级，落盘路径 |

---

## 附录：假设预览 API 快速参考

### POST /api/companies/{id}/assumption-preview

**请求**：
```json
{
  "patches": [
    { "pointer": "/income/gpm/values/0", "old_value": 0.35, "new_value": 0.38 }
  ]
}
```

**响应**：
```json
{
  "revenue_view": { "revenues": {...}, "yoy": {...}, "segments": [...] },
  "result_rows": [ {"label":"营业收入", "values":{"2025":...}} ],
  "errors": []
}
```

- `revenue_view` 是分线收入重算结果（`src/revenue_fold.project_leaf` 驱动）
- 失败时 `errors` 有内容，`revenue_view` 可能为 null，前端回退到旧值

### POST /api/companies/{id}/assumption-brief

**请求**：
```json
{
  "patches": [...],         // 同 assumption-preview
  "preview_summary": {}     // 可选，试算摘要（不影响 prompt 生成）
}
```

**响应**：
```json
{ "prompt": "/frontend-edit 进入前端编辑模式，基于当前核心假设.md 更新 ..." }
```

这段 prompt 直接复制到 Claude 对话框触发 `/frontend-edit`。`label`/`path` 由后端从 `_editable_cells_by_pointer` 反查，`unit` 不在 prompt 里（由 `/frontend-edit` 从 knobs 块读）。
