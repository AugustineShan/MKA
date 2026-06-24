# 重资产排程前端展示 tab — 设计文档

> 日期:2026-06-24
> 关联:`docs/superpowers/specs/2026-06-24-da-skill-design.md`(后端 da_roll/da_schedule 契约)
> 范围:前端 `app/` + 后端 `src/workbench.py`,只读展示重资产 DA 排程。不含编辑能力。

## 1. 背景与问题

`/da` skill 产出 `Agent/da_schedule.yaml`(假设层)与 `Agent/recon/da_facts_latest.json`(事实层),`src.forecast` 消费后把 `da_series` 注入 `Agent/.modelking/forecast_params.yaml`(结果层)。三层文件已落盘,但:

- **前端无展示**:`src/workbench.py` 完全没读这三个文件,`/api/companies/{id}` 响应不含任何 da 字段。用户在 workbench 看不到重资产排程。
- **通用性焦虑**:每个公司折旧类别千奇百怪(类别数/年限/单位/拆分层级),如何不 hardcode。

## 2. 核心设计原则:声明驱动,零公司特判

"千奇百怪"已被数据模型消化——三个文件都是声明式、结构固定的:

| 文件 | 形状 | "千奇百怪"载体 |
|---|---|---|
| `da_schedule.yaml` | `ppe.categories[]` 列表 + `expansion_plan{年:{cat:amt}}` | 公司声明几类就几类 |
| `da_facts_latest.json` | `{年:{类别:{gross/accum/net/增减}}}` | 同上 |
| `forecast_params.yaml["da_series"]` | `[{period, ppe_dep, fix_net, cip, capex, split}]` | 逐年序列,字段固定 |

**渲染铁律:一行一个声明的类别。** 类别名(房屋及建筑物/机器设备/...)从数据来,绝不进代码。N 类→N 行,换公司自动适配。这与设计规范 §5 的 stash renderer(按 JSON 结构类型分派 + 兜底)同构,继承项目第一原则"通用性高于一切"。

**唯一条件分支**:`da_view ? 渲染 tab : 不渲染`——结构性开关(`da_schedule.enabled`),非公司特判。

## 3. Tab 放置

- 新增第 **7** 个顶级 tab `{ key: "da", label: "重资产排程" }`,追加在 `tabs` 数组末尾(现 6 个:overview/yaml1/statements/dcf/reverse/quarterly)。
- `TabKey` 联合类型加 `"da"`。
- **条件渲染**:仅当 `/api/companies/{id}` 返回的 `da_view` 非 null 才渲染该 tab;否则 tab 列表不含它(轻资产公司界面零变化)。
- 注:设计规范 §2"固定五个顶级 tab"已 stale(现有 6 个),本设计追加为 7 个,顺序在末尾。

## 4. 后端:`da_view` 装配(workbench.py)

在 `/api/companies/{id}` 的公司详情组装里新增 `da_view` 字段。**仅当 `Agent/da_schedule.yaml` 存在且 `enabled: true` 才装配**,否则 `da_view = None`。

### 4.1 数据源(三个磁盘文件,只读装配,不重算)

```
da_schedule_path(company_dir)          → da_schedule.yaml   (假设层)
recon/da_facts_latest.json             → da_facts           (事实层,可选)
.modelking/forecast_params.yaml["da_series"] → da_series    (结果层,可选)
```

### 4.2 payload 结构

```python
da_view = {
  "enabled": True,
  "base_year": 2025,
  "stock_strategy": {"mode": "perpetual_renewal", "net_growth_rate": 0.0},
  "categories": [
    {"name": "房屋及建筑物", "life_years": 20, "salvage_rate": 0.05,
     "base_gross": 2222.666, "base_accum_dep": 578.130,
     "base_net": 1644.536, "base_cip": 0.0,
     "policy_dep": 105.577}   # = base_gross*(1-salvage)/life,后端算
  ],                          # N 类 N 元素,数据驱动
  "scale": 0.952,              # = base_reported_dep / Σ policy_dep
  "base_reported_dep": 424.708,# clean_annual depr_fa_coga_dpba(base 年)
  "base_cip_to_fixed": {"2026": {"机器设备": 19.415}},
  "expansion_plan": {
    "2026": {"capex_by_cat": {"机器设备": 120.0, "房屋及建筑物": 80.0},
             "cip_to_fixed": {}},
    ...
  },
  "terminal": {"capex_da_ratio": 1.0, "perpetual_growth": 0.025},
  "da_series": [...] | None,   # forecast_params.yaml["da_series"];未重跑→None
  "normalization": {"passed": True, "reason": "normalized"} | None,
  "facts": {                   # da_facts_latest.json,可选,折叠证据区用
    "ppe_detail": {...},
    "roll_forward_checks": [...],
    "policy": {...}
  } | None
}
```

### 4.3 边界与错误处理

- `da_schedule.yaml` 缺失或 `enabled: false` → `da_view = None`,前端不渲染 tab。
- `da_schedule.yaml` 存在但 `base_year ≠ defaults.base_period` → **workbench 用 `yaml.safe_load` 直读 da_schedule.yaml,不走 `src.da_roll.load_da_schedule`**(后者会抛 `DaAlignError`,那是 forecast 运行时的硬校验,展示层不该被它阻断)。`da_view` 照常装配,在 payload 里加 `align_warning: "base_year ≠ defaults.base_period"` 字段,前端在 §1 顶部 `--red` 标注(展示层诚实标注,不阻塞、不静默)。
- `forecast_params.yaml` 不存在或无 `da_series` 键(用户尚未重跑 forecast)→ `da_series=None`、`normalization=None`。前端 §3 显示"请先 `py -m src.forecast --ticker ...` 重跑生成 da_series"占位,§1/§2 正常展示。
- `da_facts_latest.json` 缺失 → `facts=None`,§4 证据区隐藏。
- 装配失败(文件损坏)→ `da_view` 内 `error` 字段塞异常摘要,前端显 `.error-banner`,不崩整个公司详情。

### 4.4 单位

`da_schedule.yaml` 与 `da_series` 已是百万元(与 clean_annual/defaults 同口径,见 da skill 设计 §6.6)。`da_facts` 是元,后端装配时 `÷1e6` 转百万元再塞 `facts`。payload 全程百万元,与前端其他表格一致。

## 5. 前端:三段 + 一折叠证据区(全部只读)

复用现有 `.financial-table` / `table-scroll` / `<details>` 组件,守规范 §3-§4。新增组件建议放 `app/src/` 现有结构内(不新开目录),命名 `DaSchedule.tsx`(或并入 App.tsx 既有 tab 渲染分支,视实现期决定)。

### §1 PP&E 存量快照(base 年)

- 表:行 = `categories[]`(N 行,数据驱动),列 = [类别名 / 年限 / 残值率 / 原值 / 累计折旧 / 净值 / CIP / 政策年折旧]。尾行合计(原值/累计折旧/净值/CIP/政策折旧列求和)。
- 顶部 eyebrow:`存量策略: 永续更新 · g=0.0` + `scale=0.952(披露 425 / policy 446)`。
- 数字 `--mono` 右对齐;比率(残值率)百分号展示。

### §2 扩张 capex 排程 + 转固

- 两张年×类别矩阵,年轴 = base+1 … explicit_end(复用 `yaml1_assumptions_view.terminal.explicit_end`,无则 fallback 全部预测年):
  - `capex_by_cat`(投资现金流出,行=类别 列=年)
  - `cip_to_fixed`(转固起折旧,同结构)
- `base_cip_to_fixed` 单独小表(年×类别),标注"存量 CIP 转固"。
- 这是分析师假设输入层,只读展示。

### §3 da_series 结果(逐年)

- 表:行 = `da_series[]`(年),列 = [年 / PP&E 折旧 / 固定资产净值 / CIP 余额 / capex 合计 / 拆分(维持·扩张·有机)]。
- 预测年份带 E 后缀、纯黑底白字表头(规范 §4.3)。
- 末行/表下挂终值归一化门结果:`normalization.passed` → 绿色 `passed`;`false` → `--red` + reason(规范:不静默放行,标偏差方向)。
- `da_series=None` → 整段替换为占位提示卡:"请先 `py -m src.forecast --ticker 002946.SZ` 重跑生成 da_series",§1/§2 不受影响。

### §4 历史 roll-forward 证据(折叠,默认关)

- `<details>` 折叠,默认 closed(规范 §8)。
- 内容:da_facts 的 per 类别 × 近 5 年 roll-forward + policy 年限残值率区间。**字段名以 `da_facts_latest.json` 实际键为准**(PP&E 走 `roll_forward_checks[]` 的 `sub_ledgers.{gross,accum,impair}.{opening,increase,decrease,closing}` + `net_opening/net_closing/closed`;CIP 走各项目 `opening_net/increase/decrease/closing_net/closed`);上文"期初净值/本期增加/本期折旧/本期减少/期末净值"为概念描述,实现时映射到真实键,不另造命名。
- `closed:false` 的项 `--red` 标注(诚实于不闭合,如新乳业 2025 昆明雪兰)。
- `facts=None` → 整段隐藏。

### 顶部提示条

tab 顶部一条 `.activity` 风格提示:`ⓘ 这是 /da 产出的排程展示。改假设请跑 /da <公司>;重算请跑 py -m src.forecast --ticker <代码>`。明确只读边界。

## 6. 风格一致性(守规范 §3-§4 + §9 禁忌)

- 色系只用 `--blue/--red/--secondary`;负数 `--red`;数字 `--mono` 右对齐。
- 年份表头纯黑底白字 + 预测年 E 后缀;历史|预测分界 2px `--blue` 竖线(若有历史锚行)。
- 折叠用原生 `<details>`;无渐变/无图标/无浮夸阴影。
- 类别名、年限、残值率全部从数据来;代码内零公司名/业务线名特判。
- 通用性自检:renderer 里不得出现"新乳业""乳业""房屋及建筑物"等字面量(类别名只能来自 `categories[].name`)。

## 7. 不做(YAGNI)

- ❌ 不做就地编辑(da_schedule 编辑走 `/da` 商议协议,与 yaml1/核心假设一致,前端不写回,规范 §9)。
- ❌ 不做敏感性拖动(那是 DCF tab 的职责)。
- ❌ 不做 da_series 重算(只读 forecast 产物;重算走 `py -m src.forecast`)。
- ❌ 不为 da_schedule 新增 patch/写回协议。

## 8. 测试

- 后端:`tests/test_workbench_da_view.py` —— 造一个临时公司目录,写最小 da_schedule.yaml + forecast_params.yaml(含/不含 da_series)+ da_facts,断言 `da_view` 装配正确(enabled/false→None、da_series 缺失→None、N 类→N 元素、scale 计算、单位换算)。用新乳业真实产物做集成断言。
- 前端:`npm run build` 过 TS;手测轻资产公司(无 da_schedule)tab 不出现、重资产公司(新乳业)tab 出现且四段渲染、da_series 缺失占位正常。

## 9. 改动清单

- `src/workbench.py`:新增 `_da_view(company_dir)` 装配函数 + 在公司详情 dict 里挂 `da_view`。
- `app/src/types.ts`:`TabKey` 加 `"da"`;新增 `DaView` 等类型。
- `app/src/App.tsx`:`tabs` 数组追加 `{key:"da",label:"重资产排程"}`;新增 `da_view` prop 透传;条件渲染 tab + `DaSchedule` 组件。
- `app/src/`(新文件或并入):`DaSchedule` 组件(§1-§4 渲染)。
- `app/src/styles.css`:复用现有表格类,按需补少量 DA 专用样式(终值门 passed/failed 状态)。
- `docs/前端设计规范.md`:§2 tab 表更新为 7 个(标注重资产排程为条件 tab)。
- `docs/数据流水线.md` / `docs/ARCHITECTURE.md`:同步 workbench 暴露 da_view 的变化(项目约定)。
