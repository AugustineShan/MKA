---
name: frontend-edit
description: 接收前端试算变更，定点回写核心假设.md（IS旋钮改正文预测行+knobs块；terminal.perpetual_growth / terminal.fade.path_targets.{field} 改 terminal 段标量+中期段 fade 描述）+ 定点 patch yaml1 对应旋钮值，再跑 src.forecast 覆盖 Agent/forecast/ 并通过 forecast 派生导出公司根目录 *Model-YYMMDD.xlsx。旋钮值小改不跑 compiler。不读定调/活跃素材/年报，不先押再问，只做安全定点 patch。旋钮值变更致叙事漂移时强制分析师更新假设基础（三件套/来源与裁决）后再跑 forecast；每次跑 forecast 前后强制重新评估 fade 期合理性（方向/量级/narrative 一致性），矛盾则要求分析师 patch path_target / 确认反转 / 拒绝；派生回显从 forecast 输出回填。
argument-hint: [无需参数，从 prompt 文本解析]
allowed-tools: Read, Grep, Glob, Edit, Write, Bash
---

# /frontend-edit — 前端试算变更定点回写器

你是一把手术刀，不是研究员。前端工作台已替用户完成试算（assumption-preview 内存重算），吐出一段含「进入前端编辑模式」的 prompt 文本。你的职责：**把这段 diff 安全回写到人话权威层 `核心假设.md`，定点 patch yaml1 对应旋钮值，再跑 forecast 并验收公司根目录 `*Model-YYMMDD.xlsx` 导出**。不读定调/活跃素材/年报，不动态加载核心假设生成器，不先押再问——那些是 /ka 的活，不是你的。

**旋钮值小改不跑 compiler**：compiler 产物 = 旧 yaml1 + 该旋钮值变化，定点 patch yaml1 等价且保留格式/注释，无需全量重译。结构性变更（新增/删旋钮、改参数化、改 terminal 长度）不在本 skill 范围，走 /adj incremental + /comp。

本 skill 是定点手术刀（不自行创作判断文本；叙事漂移时强制分析师提供更新后的假设基础并转录——转录不等于创作）,不加载完整 A/B;仅适用 `核心纪律` A4(direct yaml1 patch 边界 + 三处同源 tie-break),纪律以此为准。direct yaml1 patch 的完整边界见 `skills/核心纪律_skill_v*.md`（版本号最大的那份，按 `vN` 整数比较取最大；与其它启动器同约定，勿钉死 v1）A4：白名单不可加宽；`核心假设.md` 是 canonical，yaml1 是派生缓存；三处不同源时 md 赢，停止并回到 `/comp`，不得继续手 patch yaml1 去凑一致。

## 触发

输入含「**进入前端编辑模式**」标志（前端 prompt 开头 `/frontend-edit 进入前端编辑模式...`）。命中即走本流程；这不是 /ka 的分叉，/ka 已不识别此标志。

## 输入（从人话 prompt 文本解析）

prompt 文本形如：
```
/frontend-edit 进入前端编辑模式，基于当前核心假设.md 更新 {公司} 的假设并更新DCF

关键纪律：
- 修改人话权威层 `核心假设.md`（正文预测描述 + 末尾 knobs 块）。
- 保持原有结构、历史事实、来源说明、业务线命名和口径说明。
- 同步定点更新 yaml1 对应旋钮值（小改不跑 compiler）。
- 跑 forecast 覆盖 Agent/forecast/，并输出公司根目录 `*Model-YYMMDD.xlsx` 模型。

核心假设路径：{core_path}
当前 yaml1 路径：{yaml1_path}

前端试算变更：
- {label} ({path}) {year}: {old} -> {new}
- ...
```

解析出：
- **核心假设路径**（`核心假设路径：` 行）
- **yaml1 路径**（`当前 yaml1 路径：` 行）：必须逐字使用 prompt 给出的路径。缺失、不存在、不在该公司 `Agent\` 下、或与当前最新 yaml1 不一致时,**停止并要求前端/用户刷新工作台**,不得静默切到最新 yaml1。
- **变更列表**：每条从 `- {label} ({path}) {year}: {old} -> {new}` 解出 label / path / year / old_value / new_value。
- **unit 不从 prompt 读**（prompt 里没有），按 path 查下方「旋钮定位与白名单」节（unit 从实际 knobs 块 `unit` 字段读）。

## 纪律（硬守）

- 改人话权威层 `核心假设.md`（正文预测行 + knobs 块，同源回声一字不差）。
- **同步定点 patch yaml1 对应旋钮值**（保留格式/注释，不跑 compiler）。yaml1 不做会计化对齐/结构变更——那走 /ka + /comp。
- 保持原有结构、历史事实、来源说明、业务线命名、口径说明——**只动旋钮数值**；唯一例外见「叙事漂移与假设基础强制更新」节：旋钮值变更致叙事漂移时，强制分析师更新该旋钮的假设基础（三件套为什么/来源与裁决/预测行定性括注），frontend-edit 转录不创作；派生回显（营业收入合计/g1/归母 sanity/fade 路径）由 forecast 输出回填。
- 改完跑 forecast 覆盖 `Agent/forecast/`，并验收 `src.forecast` 派生导出的公司根目录 `*Model-YYMMDD.xlsx` 模型。
- **单位口径不同**：md knobs 块用百分数（pct ×100）；yaml1 用小数（直接用 prompt 的 new_value，不转换）。
- `knobs` 块完整语法以 `docs/knobs块契约.md` 为准；本 skill 只允许定点改已有条目的 `values[i]`。
- `核心假设.md` 是 canonical，yaml1 是派生缓存。三处同源失败时停止，回到 `/comp`，不要手 patch yaml1 去凑一致。
- **old_value 前置核对**：任何写入前,必须确认 prompt 的 `old_value` 与当前 yaml1、md knobs、md 正文旧值一致（按 unit 做小数/百分数转换）。旧值不一致说明前端基于过期状态,立即停止并要求刷新,不得继续 patch。

## 步骤

1. **解析输入**：路径 + 变更列表（每条：label / path / year / old_value / new_value）。
2. **锁定 prompt yaml1**：读取 `当前 yaml1 路径` 指向的文件；若它不是当前 `Agent\yaml1_*.yaml` 最新文件,停止并要求前端/用户刷新,不得改用另一个 yaml1。
3. **读 核心假设.md**：定位末尾 ` ```knobs ` 块、`horizon`、抬头（显式预测/衰减期至/永续）、`## 往后几年(中期)· 三段式` 段。
4. **old_value 前置核对**：逐条确认 yaml1 当前值 == prompt `old_value`，且 md knobs/正文旧值换算后也 == prompt `old_value`。任一不一致 → 报错停止。
5. **逐条 patch md**（按 path 分流，见下）：改正文预测行 + knobs 块（或 terminal 抬头+中期段）。
6. **md 同源核对**（IS 旋钮）：正文值 == knobs `values[i]`，不一致 → 报错停止。terminal.perpetual_growth / terminal.fade.path_targets 无 IS 正文预测行同源核对（path_target 回显在 fade 描述，归 fade 合理性 gate / 第12步回填）。
7. **归档旧稿**（核心假设.md 编辑归档铁律，见项目 CLAUDE.md 最开头）：先 `py scripts/ka_archive.py "<核心假设路径>"` 把旧稿移到 `companies\{公司}\Agent\KAhistory\`（tracked 用 git mv 保历史，撞名加 `-HHMMSS`），根目录不剩旧稿。
8. **写今日新稿**：Write 到 `companies\{公司}\{公司名}-{今日YYYYMMDD}-核心假设.md`（**文件名日期必须是今日**；参考稿则 `…核心假设参考.md`）。禁止 Write 覆盖旧稿路径、禁止沿用旧日期文件名。
9. **定点 patch yaml1**：
   a. **复制 prompt yaml1**：以 prompt 给出的 `当前 yaml1 路径` 为唯一 base。若文件名日期 < 今日 → cp 到 `yaml1_{公司名}_{今日YYYYMMDD}.yaml`；今日 yaml1 已存在且就是 prompt yaml1 → 直接改；今日 yaml1 已存在但不是 prompt yaml1 → 停止,要求刷新工作台。
   b. **逐条 patch yaml1**：按下方「旋钮定位与白名单」节用 Grep（`src: "#{线}"` 或 anchor/path）定位旋钮 values 行，Edit `values[year_index]`。**yaml1 用小数（prompt new_value 不 ×100）**。terminal.perpetual_growth 改 `terminal.perpetual_growth` 标量；terminal.fade.path_targets.{field} 改 `terminal.fade.path_targets.{field}` 标量（小数）。
   c. **三处同源核对**：IS 旋钮 yaml1 `values[i]`（小数）== prompt `new_value` == md knobs `values[i]`/100；terminal 标量（perpetual_growth / path_targets.{field}）yaml1 标量 == prompt `new_value` == md knobs 块对应标量（均小数，不×100）。不一致 → 报错停止。
   d. **确定性三源校验（A4 强制闸门）**：跑 `py -m src.yaml1_fidelity_check "<今日yaml1>" "Agent\defaults.yaml" "<今日核心假设.md>"`。exit 1（BLOCK:md↔knobs↔yaml1 双射 FAIL）→ 报错停止,**md 赢,回 `/comp` 重编译,不跑 forecast**;exit 0（PASS）才进第10步。详情读 `Agent\.modelking\yaml1_fidelity_report.json`。
10. **叙事漂移检测与假设基础强制更新（BLOCKING gate，详见「叙事漂移与假设基础强制更新」节）**：对每个变更旋钮，在其 `### {段名}` 段内检测定性假设基础（预测行括注 / 三件套为什么 / 来源与裁决）是否与新值矛盾。无漂移 → 进第11步。有漂移 → **停止，不跑 forecast**：向分析师报告漂移旋钮+新值+矛盾旧基础原文（file:line），要求提供「更新后的假设基础」（更新 / 确认旧基础仍成立带理由 / 拒绝）。分析师回复后转录（更新→改写三件套为什么与来源与裁决；确认→加「假设基础复核」一行；拒绝→停止不标记完成），再进第11步。整体 thesis 方向反转（多线同步翻转 / terminal 结构 / 整体推翻，见 `docs/旋钮白名单与结构判定.md` §三）不属漂移，弹回 /ka 重建。
11. **fade 期合理性重新评估（BLOCKING gate，详见「fade 期合理性重新评估」节）**：每次 frontend-edit 必须重新评估改完之后 fade 期是否合理——旋钮值变更（尤其 IS 旋钮 gpm/费用率）会改变显式期末值，若 `terminal.fade.path_targets.{field}` 未同步，fade 期可能方向反转或量级失真。对所有受 fade 影响的 field（`terminal.fade.path_targets` 登记项 + `fade_paths` 路径），取显式期末值 vs path_target vs narrative 方向，检测方向反转 / 量级失真 / narrative 矛盾。无矛盾 → 进第12步。有矛盾 → **停止，不跑 forecast**：报告矛盾 field + 显式期末值 + path_target + 反向方向 + narrative 原文（file:line），要求分析师 patch path_target（给新值，按「terminal.fade.path_targets.{field}」分流 patch md+yaml1，三处同源，再跑 fidelity）/ 确认反转成立（给理由，中期段加「fade 方向复核」行）/ 拒绝。解决后进第12步。
12. **跑 forecast + 验收模型导出 + 派生回显回填 + fade 期 post-forecast 核对**：`py -m src.forecast --yaml1 "companies/{公司名}_{代码}/Agent/yaml1_{公司名}_{今日YYYYMMDD}.yaml"`，覆盖 `Agent/forecast/`。随后读取 `Agent/forecast/run_manifest.json`，要求 `company_excel_export_status == "written"`、`company_excel_output_path` 非空且文件存在；若 status 为 `failed` / `skipped` 或路径不存在，原样报错，不能把本次 `/frontend-edit` 说成完整完成。**派生回显回填**：读 `Agent/forecast/forecast_is.csv` + `derived_metrics_annual.csv`，把 md 依赖引擎的派生回显回填以保持 md 内部一致——营业收入合计预测行（年度收入+yoy）、g1 CAGR（时间轴四数/中期段/stash 核对项多处）、归母 sanity（利润检查线）、fade 期 yoy 路径/落差描述（若 g1 变化致 fade 重算）。转录引擎输出，不自行做引擎数学。**fade 期 post-forecast 核对**：取每个 path_target field 的 fade 期逐年值（derived_metrics_annual.csv），核对实际 fade 终点（`fade.to_year` 年）== path_target（容差 0.005）、fade 期方向与第11步 pre-forecast 判断一致；不一致 → 报错（引擎行为与 knobs 声明不符，可能 fidelity 漏检或引擎 bug，停止排查）。把实际 fade 路径回填到 md 中期段 fade 描述。
13. **汇报**：每条变更（旋钮 / 年份 / 旧值→新值 / md正文&knobs&yaml1 三处是否同源）、**假设基础更新情况（哪些旋钮漂移、分析师更新/确认/拒绝）**、**fade 期合理性评估结论（哪些 field 矛盾、分析师 patch path_target/确认/拒绝、post-forecast 核对结果）**、forecast 每股价值与 `Agent/forecast/` 路径、Excel 模型导出状态与 `*Model-YYMMDD.xlsx` 路径、派生回显回填了哪些项；任何报错原样摆出。

汇报口吻像手术回执，不像 patch 日志：先说“我只改了哪几个旋钮、没有碰哪些结构、三处同源是否通过、DCF 新结果是什么、模型文件是否写出”，再列路径。不要把 yaml1 片段或全文 diff 贴满屏；用户需要时再展开。

## 逐条 patch 分流（md 侧）

### IS 旋钮（path 命中解析规则，见「旋钮定位与白名单」节）

a. **路径映射**：按「旋钮定位与白名单」节解析 path → 在实际 md knobs 块定位 `{anchor, sub, family, unit}`。path 不匹配任一模式，或 knobs 块无该条目 → **报错停止，不要猜**。
b. **单位转换（md 侧）**：`unit: pct` 前端小数 → md 百分数（×100）；`unit: abs_mn` 直接用值。换算规则的唯一真源是 `src/unit_convert.py`（`to_md_display(value, unit)` = 小数→md 展示值；`to_decimal` 为其逆），与 yaml1_fidelity_check 同源——别在别处手抄 ×100 方向。
c. **年份定位**：`horizon` 首年 = `values[0]`，按年份求索引 i。year 不在 horizon 内 → 报错停止。
d. **改 knobs 块**：找到 `{anchor, sub}` 行，把 `values[i]` 替换为新值（百分数）。找不到该行 → 报错停止。
e. **改正文**：在 `### {anchor 对应段名}` 段落下定位 sub 预测行（如 `- 销量 yoy:`），**只改这一旋钮预测行**——正文数值是 knobs 值经 `to_md_display` 的派生回显（knobs 块为 md 内的值源，正文数字回声它，故步骤 6 的同源核对必过），派生行（标"派生·引擎算·非翻译输入"的收入/毛利率/占比）不动，引擎会从旋钮重算。替换对应年份的值。若原行是"全程统一 X%"而本次只改一年，把该行改写成逐年列举（其他年份保留原值）。找不到对应预测行 → 报错停止。

### terminal.perpetual_growth（定点 patch）

md 侧改两处（不进 knobs 块、无 knobs 同源核对）：
- 抬头「永续 [x]%」→ 新值（小数×100）。
- `## 往后几年(中期)· 三段式` 段「终值:永续一个点(x%)」→ 新值。
yaml1 侧改 `terminal.perpetual_growth` 标量（小数，不×100）。

### terminal.fade.path_targets.{field}（定点 patch）

fade 端点**数值**（非结构参数——fade 机制 kind/to_year/target_growth 不动），可定点 patch。md 与 yaml1 均用小数（不×100，同 terminal 块其他标量）。改它通常因为显式期对应旋钮值已改、fade 端点需同步以保持方向一致（见「fade 期合理性重新评估」节）。
- md 侧改两处：
  - knobs 块 `terminal.fade.path_targets.{field}: {旧}` → 新值（小数）。
  - 中期段（`## 五、中期/terminal`）引用该 path_target 的 fade 描述行（如"2028 末 X% → 2034 Y%，略上行/回落"）→ 同步新值与新方向（方向定性随 fade 合理性 gate 结论，数值回显归第12步）。
- yaml1 侧改 `terminal.fade.path_targets.{field}` 标量（小数）。
- **三处同源核对**：md knobs 块 `path_targets.{field}` == yaml1 `terminal.fade.path_targets.{field}` == prompt `new_value`（均小数，不×100）。中期段 fade 描述为派生回显，按 fade 合理性 gate / 第12步回填。无 IS 正文预测行同源核对（path_target 不对应单一年份预测行）。

### terminal.explicit_end / terminal.fade.to_year / terminal.fade.target_growth（报错停止）

这些改的是 terminal 结构或衰减交接逻辑，会连带要求中期段重新拍板，可能同步影响 fade 期展开和所有 IS 旋钮远端解释——不是定点 patch 能安全做的。**报错停止**，提示：「显式期/衰减期/衰减交接增速变更是结构性改动，请走 /adj incremental 流程」。

> 注意：`terminal.fade.path_targets.{field}` **不**属此停止列表——它是 fade 端点数值，可定点 patch（见上节）。`fade.to_year` 才是结构边界（改衰减期长度）。

## 旋钮定位与白名单（file-derived，不维护枚举表）

**不再维护 path→anchor/family/unit/yaml1Locator 的枚举表**——枚举表会与白名单文档/实际 yaml1 漂移（`revenue_abs` 事件即此：表漏列 abs 族，但白名单文档 §一 已登记、实际 knobs 块/yaml1 也有，硬协议却误报"映射不到→停"）。改用「path 解析规则 + 实际文件定位」：path 解析出 (segment/field/科目)，family/unit/anchor/yaml1Locator 全部从**当前公司的 md knobs 块 + yaml1 实际内容**读出。新增 segment 级 field（`revenue_abs` 或未来任意 field）只要被 /comp 写进 knobs 块/yaml1，本 skill 自动支持，**无需改本节**。

### path 解析规则（family-agnostic，参数化，不枚举具体 field/线/科目）

| path 模式 | 解析 | 说明 |
|---|---|---|
| `income.revenue.{线}.{field}` | segment={线}, field={field} | field∈{revenue_yoy, revenue_abs, volume, price, …}，**不枚举**。segment-knob（growth/abs，值在 `knobs.{field}`）vs factor（factor_yoy，值在 `factors[key={field}].projection.values`）由**实际 yaml1 判**——`knobs.{field}` 存在→knob；`factors[key={field}]` 存在→factor |
| `income.gpm` | top-level gpm | gpm 族 |
| `expense.{项}.rate` | cost_rate, 费用项={项} | cost_rate 族；{项}∈{销售费用/管理费用/研发费用/营业税金及附加/…} 不枚举，{项}→yaml1 key 以实际 yaml1 为准（Grep `src:`） |
| `below_op.{科目}.abs` | below-OP abs, 科目={科目} | below_line_abs/op_adj_abs/cost_abs 族；{科目}∈{资产减值损失/信用减值损失/其他收益/投资净收益/公允价值变动净收益/资产处置收益/营业外收入/营业外支出/…} 不枚举 |
| `tax.rate` | effective_tax_rate | tax_rate 族 |
| `minority.rate` | minority_ratio | minor_rate 族 |
| `financial_expense.other_fin_exp_abs` | 非息财务费用 / other_fin_exp_abs | fin_exp_abs 族 |
| `terminal.perpetual_growth` | terminal 标量 | terminal 族（永续增速） |
| `terminal.fade.path_targets.{field}` | fade 端点标量 | path_target 族（fade 期收敛终点；{field} 如 income.gpm，不枚举）。这是**数值**非结构参数，可定点 patch；md knobs 块 terminal 段与 yaml1 均用小数（不×100，同 perpetual_growth） |

> `{线}`/`{项}`/`{科目}`/`{field}` 为参数化占位——任意业务线/科目/factor 名走同一规则，**不再因"表没列该 path"而停**。新增**顶层模式**（如全新 `income.xxx.{y}` 结构，非现有模式的新参数值）才需登记，见下。

### 白名单闸门（file-derived）
path 允许定点 patch 的充要条件（三者都满足）：
1. path 匹配上表某一**模式**；且
2. 目标旋钮在**当前 md knobs 块**中存在（IS segment：Grep `anchor: "#{线}"` 找到带 `values:[...]` 的条目；gpm/cost_rate/tax/minority/fin_exp：Grep 对应 anchor 找到条目；factor_yoy factor：knobs 块无独立条目，看 yaml1 `factors[key={field}]` 存在；terminal.fade.path_targets.{field}：knobs 块 `terminal:` 段下 `path_targets:` 找到 `{field}:` 条目）；且
3. 目标旋钮在**当前 yaml1**中存在（segment `knobs.{field}`/`factors[key={field}].projection.values`，或 top-level knob path，或 `terminal.fade.path_targets.{field}`）。

任一不满足 → **停**（真结构性变更或 prompt 拼写错误，走 `/adj incremental` 或修 prompt，不降级硬 patch）。**不再因 skill 表与白名单文档漂移而误停**——表已废，以实际文件为准。新增**顶层模式/family** 的登记入口仍是 `docs/旋钮白名单与结构判定.md` §一（/comp 层强制），本 skill 不复制该清单；现有模式下新增 field/线/科目值无需登记。

### md knobs 定位（读实际 knobs 块）
- IS segment 旋钮：Grep `anchor: "#{线}"`，取该条 `sub`/`family`/`unit`/`values`；`values[i]` 即旋钮值。factor_yoy 族 factor 在 knobs 块无独立条目（其 md 正文预测行在 `### {线}` 段内定位）。
- gpm/cost_rate/tax/minority/fin_exp：Grep anchor（`#整体毛利率`/`#{费用项}`/`#有效税率`/`#少数股东损益`/`#其他财务费用`），取 `values`。
- **unit 转换从 knobs 块 `unit` 字段读**：`pct` → 前端小数×100 写 md；`abs_mn` → 直接用值。不查表。
- terminal 标量（perpetual_growth / fade.path_targets.{field}）：在 knobs 块 `terminal:` 段下定位（`perpetual_growth:` / `path_targets:` 下的 `{field}:`），均小数不×100。

### yaml1 定位（读实际 yaml1，Grep 锚点）
- segment 旋钮：Grep `src: "#{线}"` 定位 segment；growth/abs 族 → `segments.{线}.knobs.{field}`；factor_yoy 族 → `segments.{线}.factors[key={field}].projection.values`。
- top-level：`income.gpm.values` / `income.cost_rates.{key}.values` / `income.effective_tax_rate.values` / `income.minority_ratio.values` / `income.financial_expense.other_fin_exp_abs.values`（{key}/{field} 以实际 yaml1 命名为准，Grep 锚点定位）。
- below-OP abs：Grep 科目名/`src:` 定位 `income.operating_adjustments_abs.{field}` / `income.below_line_abs.{field}` / `income.cost_abs.{field}`，以实际容器为准。
- terminal.perpetual_growth：`terminal.perpetual_growth`（标量，非 values）。
- terminal.fade.path_targets.{field}：`terminal.fade.path_targets.{field}`（标量，非 values；Grep `path_targets:` 定位）。

> 定位时用 Grep 拿上下文（segment `src:`、旋钮 path、`unit`），确认是目标旋钮行再 Edit。**只改 `values[year_index]` 一个元素（或标量），保留行内注释（如 `# 减速`）与格式。** 命名与实际 yaml1 不符 → 以实际 yaml1 为准，Grep 锚点定位，不硬猜。

## 叙事漂移与假设基础强制更新

旋钮值变更可能让该旋钮段的定性假设基础与新值矛盾（如「见底企稳小回升」配 -10%、「未取继续下滑」配继续下滑、「保守情景」配大幅上调）。**叙事漂移由 frontend-edit 主责，不弹 /ka**——但 frontend-edit 不创作判断，只强制分析师更新假设基础并转录。

### 检测范围（每个变更旋钮的 `### {段名}` 段内）
- 预测行定性括注（如「见底企稳小回升」「中性情景」「保守」）
- 三件套「为什么」「谁定」
- 来源与裁决段（候选采纳理由 / 未采用方去处）

**判漂移**：定性文字描述的方向 / 量级 / 情景与新值矛盾，即漂移。判不定时不判漂移（偏保守不误报）。预测行的数值回显（收入=…）属派生回显，归第11步回填，不属漂移。

### 强制流程（BLOCKING，第10步）
1. 检测到漂移 → **停止**：不跑 forecast。
2. 向分析师报告：漂移旋钮 + 新值 + 与新值矛盾的旧假设基础原文（逐条 file:line）。
3. 要求分析师对每个漂移旋钮提供「更新后的假设基础」之一：
   - **更新**：给新的三件套「为什么」+ 来源与裁决（与新值一致）→ frontend-edit 转录入 md（改写对应段落，不改旋钮数值、不改历史/来源说明/口径）；
   - **确认旧基础仍成立**：给理由 → frontend-edit 在该段加一行「假设基础复核：YYYY-MM-DD 分析师确认旧基础仍成立，理由：…」，不改判断文本；
   - **拒绝**：停止，不跑 forecast，不标记完成。
4. 转录后再进第11步（fade 合理性 gate）。

frontend-edit 全程不自行创作判断文本，只转录分析师强制提供的假设基础。

### 边界（仍弹 /ka）
单旋钮 / 单线漂移由 frontend-edit 强制更新假设基础处理。**整体 thesis 方向反转**（多线同步翻转 / terminal 结构 / 增长假设整体推翻，见 `docs/旋钮白名单与结构判定.md` §三）仍弹回 /ka 重建——那是重建，不是漂移。

## fade 期合理性重新评估

每次 frontend-edit 都必须重新评估"改完之后 fade 期是否合理"。旋钮值变更（尤其 IS 旋钮 gpm / 费用率 / below-OP 绝对值）会改变显式期末年值；若 `terminal.fade.path_targets.{field}` 未同步调整，fade 期会方向反转或量级失真——这是 frontend-edit 最容易留下结构性遗留的环节（典型：显式期 gpm 上调但 path_target 没动，致 fade 期 gpm 反向回落，与"结构升级尾势"叙事矛盾）。**此 gate 由 frontend-edit 主责，不弹 /adj**——path_target 现已在白名单内，可直接 patch。

### 评估对象
所有受 fade 机制影响的旋钮：
- `terminal.fade.path_targets` 中登记的 field（如 `income.gpm`）——有显式 fade 端点；
- `fade_paths` 中的路径（如 `model.revenue_yoy`）——fade 收敛到 `target_growth`；
- `hold_paths` 中的旋钮（如费用率/税率）——fade 期持有不变，**无矛盾风险**，跳过。

对每个评估对象取：显式期末年值（knobs `values[-1]` 或 forecast 末年）、path_target（或 target_growth）、`fade.to_year`、该 field 段 narrative 方向。

### 评估规则（pre-forecast，patch 后、forecast 前，第11步）
对每个 path_target field：
1. **方向一致性**：显式期 trajectory（values[0]→values[-1]）方向（升/降/平）vs fade 段（values[-1]→path_target）方向。若显式期单方向变动且 path_target 跨越 values[-1] 致 fade 反向 → flag **方向矛盾**。例：gpm 显式期 43.6%→50.5% 上行，path_target 0.475 < 0.505 → fade 期反向回落 3pct。
2. **量级合理性**：|path_target − values[-1]| 落差过大（margin 类 > 2pct、rate 类 > 1pct、abs 类 > 末年值 20%）→ flag **量级失真**（即使方向一致，落差过大也意味着 fade 期剧变，需分析师确认）。
3. **narrative 一致性**：该 field 段定性（如"结构升级尾势略上行"/"改革红利收敛"/"趋稳"）与 fade 实际方向是否一致。narrative 说"略上行"但 fade 反向回落 → flag **narrative 矛盾**。

**判矛盾**：方向反转 OR narrative 与 fade 方向不一致 → 矛盾。量级失真单独 flag 但不强制 BLOCK（方向对了量大可能是分析师意图）。判不定时不判矛盾（偏保守不误报）。

### 强制流程（BLOCKING，第11步）
1. 检测到方向/narrative 矛盾 → **停止**：不跑 forecast。
2. 向分析师报告：矛盾 field + 显式期末值 + path_target + fade 实际方向（"末值 X → 端点 Y，反向回落/上行 Z pct"）+ narrative 矛盾原文（逐条 file:line）。
3. 要求分析师对该矛盾 field 提供之一：
   - **patch path_target**：给新 path_target 值（使 fade 方向与显式期/narrative 一致，通常 ≥ 或 ≤ values[-1]）→ frontend-edit 按「terminal.fade.path_targets.{field}」分流 patch（md knobs 块 path_targets + 中期段 fade 描述 + yaml1 terminal.path_targets），三处同源，重跑 fidelity check（第9d），再进第12步；
   - **确认反转成立**：给理由（如"显式期红利见顶后回落是预期内"/"path_target 是长期稳态，显式期是周期高点"）→ 在中期段加「fade 方向复核：YYYY-MM-DD 分析师确认 fade 期 {field} 由 {末值} 反向至 {target}，理由：…」，不改 path_target 数值；
   - **拒绝**：停止，不跑 forecast，不标记完成。
4. 解决后进第12步跑 forecast。

frontend-edit 不自行决定 path_target 新值（那是分析师判断），只转录分析师给定的新值或确认理由。

### post-forecast 核对（第12步一部分）
forecast 后读 `derived_metrics_annual.csv`，取该 field fade 期逐年值，核对：
- 实际 fade 终点（`fade.to_year` 年值）== path_target（容差 0.005）；
- fade 期方向与第11步 pre-forecast 判断一致；
- 若该 field 在 `hold_paths` → fade 期值应 == 显式期末值（容差 0.005）。
任一不一致 → 报错（引擎行为与 knobs 声明不符，可能 fidelity 漏检或引擎 bug，停止排查，不静默）。把实际 fade 路径回填到 md 中期段 fade 描述行。

## 硬协议（违反即停，绝不静默）

- path 不匹配任一解析模式，或目标旋钮在实际 md knobs 块/yaml1 中不存在 → 停（真结构性变更或 prompt 拼写错误，走 `/adj incremental` 或修 prompt）。**不再维护 path 枚举表，不再因表与白名单文档漂移而误停**（见「旋钮定位与白名单」节）。
- prompt `当前 yaml1 路径` 缺失/不存在/不在公司 `Agent\` 下/不是最新 → 停,要求刷新工作台；不得自动切到最新 yaml1。
- prompt `old_value` 与当前 yaml1 或 md 旧值不一致 → 停,要求刷新工作台。
- md 正文与 knobs 不同源 → 停。
- yaml1 与 prompt/md 三处不同源 → 停；md 赢，回到 `/comp`。
- `yaml1_fidelity_check` exit 1（BLOCK）→ 停；md 赢，回 `/comp`，**不跑 forecast**。
- 叙事漂移未更新假设基础（更新 / 确认旧基础仍成立带理由）→ 停（不跑 forecast，不标记完成）。
- 不读投研材料（定调/活跃素材/年报/业务讨论）。
- 不改历史段（历史照搬，一个不动）。
- yaml1 只做旋钮值定点 patch，不做结构/会计化变更（那走 /ka+/comp）。
- 派生回显（营业收入合计/g1/归母 sanity/fade 路径）由 forecast 输出回填，不自行做引擎数学；预测行定性括注属假设基础，漂移时随分析师更新转录。
- terminal.explicit_end / fade.to_year / fade.target_growth → 停（结构/交接逻辑）。**`terminal.fade.path_targets.{field}` 不在此列**——fade 端点数值可定点 patch（见「terminal.fade.path_targets.{field}」分流节）。
- fade 期合理性矛盾未解决（patch path_target / 确认反转成立带理由）→ 停（不跑 forecast，不标记完成）。每次 frontend-edit 必须跑 fade 合理性 gate，不得跳过。
- path_target 三处不同源（md knobs 块 path_targets / yaml1 terminal.path_targets / prompt new_value）→ 停；md 赢，回 `/comp`。
- 不先押再问——前端已替用户拍板，你只执行回写；但发现 path 映射不上或结构对不上时，停下来报错，不要猜。**例外**：叙事漂移 BLOCKING gate 与 fade 合理性 BLOCKING gate 要求分析师更新假设基础 / 给 path_target 新值或确认理由，这是强制假设基础更新，不属「先押再问」。
