---
name: frontend-edit
description: 接收前端试算变更，定点回写核心假设.md（IS旋钮改正文预测行+knobs块；terminal.perpetual_growth改抬头+中期段）+ 定点 patch yaml1 对应旋钮值，再跑 src.forecast 覆盖 Agent/forecast/。旋钮值小改不跑 compiler。不读定调/活跃素材/年报，不先押再问，只做安全定点 patch。
argument-hint: [无需参数，从 prompt 文本解析]
allowed-tools: Read, Grep, Glob, Edit, Write, Bash
---

# /frontend-edit — 前端试算变更定点回写器

你是一把手术刀，不是研究员。前端工作台已替用户完成试算（assumption-preview 内存重算），吐出一段含「进入前端编辑模式」的 prompt 文本。你的职责：**把这段 diff 安全回写到人话权威层 `核心假设.md`，并定点 patch yaml1 对应旋钮值，再跑 forecast**。不读定调/活跃素材/年报，不动态加载核心假设生成器，不先押再问——那些是 /ka 的活，不是你的。

**旋钮值小改不跑 compiler**：compiler 产物 = 旧 yaml1 + 该旋钮值变化，定点 patch yaml1 等价且保留格式/注释，无需全量重译。结构性变更（新增/删旋钮、改参数化、改 terminal 长度）不在本 skill 范围，走 /adj incremental + /comp。

本 skill 是定点手术刀(不写核心假设.md 业务判断),不加载完整 A/B;仅适用 `核心纪律` A4(direct yaml1 patch 边界 + 三处同源 tie-break),纪律以此为准。direct yaml1 patch 的完整边界见 `skills/核心纪律_skill_v*.md`（版本号最大的那份，与其它启动器同约定，勿钉死 v1）A4：白名单不可加宽；`核心假设.md` 是 canonical，yaml1 是派生缓存；三处不同源时 md 赢，停止并回到 `/comp`，不得继续手 patch yaml1 去凑一致。

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
- 跑 forecast 覆盖 Agent/forecast/。

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
- **unit 不从 prompt 读**（prompt 里没有），按 path 查下方映射表。

## 纪律（硬守）

- 改人话权威层 `核心假设.md`（正文预测行 + knobs 块，同源回声一字不差）。
- **同步定点 patch yaml1 对应旋钮值**（保留格式/注释，不跑 compiler）。yaml1 不做会计化对齐/结构变更——那走 /ka + /comp。
- 保持原有结构、历史事实、来源说明、业务线命名、口径说明——**只动旋钮数值**。
- 改完跑 forecast 覆盖 `Agent/forecast/`。
- **单位口径不同**：md knobs 块用百分数（pct ×100）；yaml1 用小数（直接用 prompt 的 new_value，不转换）。
- `核心假设.md` 是 canonical，yaml1 是派生缓存。三处同源失败时停止，回到 `/comp`，不要手 patch yaml1 去凑一致。
- **old_value 前置核对**：任何写入前,必须确认 prompt 的 `old_value` 与当前 yaml1、md knobs、md 正文旧值一致（按 unit 做小数/百分数转换）。旧值不一致说明前端基于过期状态,立即停止并要求刷新,不得继续 patch。

## 步骤

1. **解析输入**：路径 + 变更列表（每条：label / path / year / old_value / new_value）。
2. **锁定 prompt yaml1**：读取 `当前 yaml1 路径` 指向的文件；若它不是当前 `Agent\yaml1_*.yaml` 最新文件,停止并要求前端/用户刷新,不得改用另一个 yaml1。
3. **读 核心假设.md**：定位末尾 ` ```knobs ` 块、`horizon`、抬头（显式预测/衰减期至/永续）、`## 往后几年(中期)· 三段式` 段。
4. **old_value 前置核对**：逐条确认 yaml1 当前值 == prompt `old_value`，且 md knobs/正文旧值换算后也 == prompt `old_value`。任一不一致 → 报错停止。
5. **逐条 patch md**（按 path 分流，见下）：改正文预测行 + knobs 块（或 terminal 抬头+中期段）。
6. **md 同源核对**（IS 旋钮）：正文值 == knobs `values[i]`，不一致 → 报错停止。terminal.perpetual_growth 无 knobs 同源核对。
7. **归档旧稿**（核心假设.md 编辑归档铁律，见项目 CLAUDE.md 最开头）：先 `py scripts/ka_archive.py "<核心假设路径>"` 把旧稿移到 `companies\{公司}\Agent\KAhistory\`（tracked 用 git mv 保历史，撞名加 `-HHMMSS`），根目录不剩旧稿。
8. **写今日新稿**：Write 到 `companies\{公司}\{公司名}-{今日YYYYMMDD}-核心假设.md`（**文件名日期必须是今日**；参考稿则 `…核心假设参考.md`）。禁止 Write 覆盖旧稿路径、禁止沿用旧日期文件名。
9. **定点 patch yaml1**：
   a. **复制 prompt yaml1**：以 prompt 给出的 `当前 yaml1 路径` 为唯一 base。若文件名日期 < 今日 → cp 到 `yaml1_{公司名}_{今日YYYYMMDD}.yaml`；今日 yaml1 已存在且就是 prompt yaml1 → 直接改；今日 yaml1 已存在但不是 prompt yaml1 → 停止,要求刷新工作台。
   b. **逐条 patch yaml1**：按下方「yaml1 旋钮定位规则」用 Grep（`src: "#{线}"` 或 anchor/path）定位旋钮 values 行，Edit `values[year_index]`。**yaml1 用小数（prompt new_value 不 ×100）**。terminal.perpetual_growth 改 `terminal.perpetual_growth` 标量。
   c. **三处同源核对**：yaml1 `values[i]`（小数）== prompt `new_value` == md knobs `values[i]`/100。不一致 → 报错停止。
   d. **确定性三源校验（A4 强制闸门）**：跑 `py -m src.yaml1_fidelity_check "<今日yaml1>" "Agent\defaults.yaml" "<今日核心假设.md>"`。exit 1（BLOCK:md↔knobs↔yaml1 双射 FAIL）→ 报错停止,**md 赢,回 `/comp` 重编译,不跑 forecast**;exit 0（PASS）才进第10步。详情读 `Agent\.modelking\yaml1_fidelity_report.json`。
10. **跑 forecast**：`py -m src.forecast --yaml1 "companies/{公司名}_{代码}/Agent/yaml1_{公司名}_{今日YYYYMMDD}.yaml"`，覆盖 `Agent/forecast/`。
11. **汇报**：每条变更（旋钮 / 年份 / 旧值→新值 / md正文&knobs&yaml1 三处是否同源）、forecast 每股价值与 `Agent/forecast/` 路径；任何报错原样摆出。

## 逐条 patch 分流（md 侧）

### IS 旋钮（path 命中映射表）

a. **路径映射**：path → knobs 块 `{anchor, sub}`。映射不上 → **报错停止，不要猜**。
b. **单位转换（md 侧）**：`unit: pct` 前端小数 → md 百分数（×100）；`unit: abs_mn` 直接用值。
c. **年份定位**：`horizon` 首年 = `values[0]`，按年份求索引 i。year 不在 horizon 内 → 报错停止。
d. **改 knobs 块**：找到 `{anchor, sub}` 行，把 `values[i]` 替换为新值（百分数）。找不到该行 → 报错停止。
e. **改正文**：在 `### {anchor 对应段名}` 段落下定位 sub 预测行（如 `- 销量 yoy:`），**只改这一旋钮预测行**——派生行（标"派生·引擎算·非翻译输入"的收入/毛利率/占比）不动，引擎会从旋钮重算。替换对应年份的值。若原行是"全程统一 X%"而本次只改一年，把该行改写成逐年列举（其他年份保留原值）。找不到对应预测行 → 报错停止。

### terminal.perpetual_growth（定点 patch）

md 侧改两处（不进 knobs 块、无 knobs 同源核对）：
- 抬头「永续 [x]%」→ 新值（小数×100）。
- `## 往后几年(中期)· 三段式` 段「终值:永续一个点(x%)」→ 新值。
yaml1 侧改 `terminal.perpetual_growth` 标量（小数，不×100）。

### terminal.explicit_end / terminal.fade.to_year（报错停止）

这俩改的是预测年数长度，会连带要求 knobs `horizon` 数组和所有 IS 旋钮 `values` 数组同步截断/补值，补值需拍新年份判断——不是定点 patch 能安全做的。**报错停止**，提示：「显式期/衰减期长度变更是结构性改动，请走 /adj incremental 流程」。

## IS 旋钮路径映射表（md knobs 侧，通用）

| 前端 path | knobs anchor | knobs sub | family | unit | md 转换 |
|---|---|---|---|---|---|
| `income.revenue.{线}.volume` | `#{线}` | 销量 | factor_yoy | pct | ×100 |
| `income.revenue.{线}.price` | `#{线}` | 吨价 | factor_yoy | pct | ×100 |
| `income.revenue.{线}.revenue_yoy` | `#{线}` | 收入 | growth | pct | ×100 |
| `income.gpm` | `#整体毛利率` | — | gpm | pct | ×100 |
| `expense.{销售费用\|管理费用\|研发费用\|营业税金及附加}.rate` | `#{费用项}` | — | cost_rate | pct | ×100 |
| `below_op.{科目}.abs` | `#{科目}` | — | below_line_abs | abs_mn | 直接 |
| `tax.rate` | `#有效税率` | — | tax_rate | pct | ×100 |
| `minority.rate` | `#少数股东损益` | — | minor_rate | pct | ×100 |

> `{线}` / `{科目}` 为业务线名 / below-OP 科目名，须与 knobs 块 anchor 一致。`below_op.{科目}` 覆盖：资产减值损失 / 信用减值损失 / 其他收益 / 投资净收益 / 公允价值变动净收益 / 资产处置收益 / 营业外收入 / 营业外支出。
> 未覆盖 path → 报错停止，不猜。前端新增旋钮族须先在此表登记。

## yaml1 旋钮定位规则（定点 patch yaml1 用，小数不转换）

| 前端 path | yaml1 定位（Grep 锚点 → values 数组） |
|---|---|
| `income.revenue.{线}.volume` | `income.revenue.segments.{线}.factors[key=volume].projection.values`（Grep `src: "#{线}"` 定位 segment） |
| `income.revenue.{线}.price` | `segments.{线}.factors[key=price].projection.values` |
| `income.revenue.{线}.revenue_yoy` | `segments.{线}.knobs.revenue_yoy`（growth 族，segment 级；非 projection.values） |
| `income.gpm` | `income.gpm.values` |
| `expense.{项}.rate` | `income.cost_rates.{key}.values`（销售费用→sell_exp / 管理费用→admin_exp / 研发费用→rd_exp / 营业税金及附加→biz_tax_surchg；以实际 yaml1 为准） |
| `below_op.{科目}.abs` | `income.operating_adjustments_abs.{field}.values` 或 `income.below_line_abs.{field}.values`（Grep 科目名/anchor 定位对应 `_abs` 容器；以实际 yaml1 为准） |
| `tax.rate` | `income.effective_tax_rate.values` |
| `minority.rate` | `income.minority_ratio.values` |
| `terminal.perpetual_growth` | `terminal.perpetual_growth`（标量，非 values 数组） |

> 定位时用 Grep 拿到上下文（segment 的 `src:` 注释、旋钮 path），确认是目标旋钮行再 Edit。**只改 `values[year_index]` 一个元素，保留行内注释（如 `# 减速`）和其余格式。**
> `{key}`/`{field}` 映射若与实际 yaml1 不符（compiler 命名变了）→ 以实际 yaml1 内容为准，Grep 锚点定位，不硬猜。

## 硬协议（违反即停，绝不静默）

- 映射不到的 path → 停。
- prompt `当前 yaml1 路径` 缺失/不存在/不在公司 `Agent\` 下/不是最新 → 停,要求刷新工作台；不得自动切到最新 yaml1。
- prompt `old_value` 与当前 yaml1 或 md 旧值不一致 → 停,要求刷新工作台。
- md 正文与 knobs 不同源 → 停。
- yaml1 与 prompt/md 三处不同源 → 停；md 赢，回到 `/comp`。
- `yaml1_fidelity_check` exit 1（BLOCK）→ 停；md 赢，回 `/comp`，**不跑 forecast**。
- 不读投研材料（定调/活跃素材/年报/业务讨论）。
- 不改历史段（历史照搬，一个不动）。
- yaml1 只做旋钮值定点 patch，不做结构/会计化变更（那走 /ka+/comp）。
- 派生行不动（收入/毛利率/占比是引擎算的）。
- terminal.explicit_end / fade.to_year → 停。
- 不先押再问——前端已替用户拍板，你只执行回写；但发现 path 映射不上或结构对不上时，停下来报错，不要猜。
