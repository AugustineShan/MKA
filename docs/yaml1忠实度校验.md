# yaml1 忠实度校验（yaml1_fidelity_check.py）

> 一句话：用 Python 初步核对 `yaml1` 是否忠实翻译自 `核心假设.md`，**只抓形变层低级错误，不碰语义级判断**。

## 它在管道里补的洞

下游 `yaml1_cleaner.py` 已经把守两件事：
- **yaml1 ↔ 历史现实**：fold 回测（分线 base 加总 ≈ clean_annual 总额）、历史年符号对账。
- **yaml1 ↔ 自洽**：结构折叠、单位、horizon。

但 cleaner **从不读 `核心假设.md`**。于是这条缝无人把守：

> 预测旋钮抄错值、漏一条旋钮、预测符号反、路径映射/嵌套错 —— cleaner 的回测锚在基年历史，**预测值不参与回测，会静默折进 DCF**。

`yaml1_fidelity_check.py` 只填这条缝（`yaml1 ↔ .md 预测意图`），不重造下游的 fold/回测。

## 三道闸

| 闸 | 比对对象 | 抓什么 | 杠杆 |
|---|---|---|---|
| **A 结构** | yaml1 单独 | 数组长度 ≠ horizon、decomposition 深度 > 2、decomposition/leaf 混用、`revenue_family`/`projection.kind` 非法、margin 二选一违反 | 算法契约代码化 |
| **B 路径+符号** | yaml1 vs `defaults.yaml` | 路径不在 defaults（发明路径或嵌套错，下游会静默丢弃）、符号与基年相反、费率越界 [0,1) | `defaults` 当符号神谕 |
| **C 值双射** | yaml1 vs `核心假设.md` | 抄错值、小数点滑位、漏译、符号反 | `src` 锚点当连接键 |

Gate C 机制：每条旋钮带 `src`（如 `src: "#销售费用"`）→ 据此定位 .md 小节 → 抽数字做**符号+量级敏感的集合核对**（yaml1 的每个值必须能在 .md 对应小节找到）。单旋钮小节取整节加粗值；多旋钮共享小节（如 营业外收入/支出）按关键词收窄防串行。

## 判定与状态

- `verdict: PASS` / `BLOCK`（有任一 `FAIL` 即 BLOCK，退出码 1）。
- 单条状态：`PASS` / `FAIL`（硬错）/ `WARN`（疑似，人工判一次）/ `UNRESOLVED`（src 定位不到小节，**举旗交人，绝不静默判 PASS**）。

## 用法

```bash
PY=/c/Users/Sheld/AppData/Local/Programs/Python/Python311/python.exe
"$PY" D:/MKA/src/yaml1_fidelity_check.py <yaml1.yaml> <defaults.yaml> <核心假设.md> [report_dir]
```

报告落盘 `report_dir/yaml1_fidelity_report.json`（默认写公司目录下 `.modelking/`）。stdout 只打 ASCII 摘要（中文走 stdout 会乱码，见 CLAUDE.md）。`/comp` 已把它接成编译后的必跑闸。

## Gate C 双模式：block-diff（无损）/ regex（脆性·回退）

Gate C 有两条路径，验证器自动路由（报告里的 `gate_c_mode` 字段标明走了哪条）：

- **block-diff（无损，优先）**：若 `.md` 含 ` ```knobs ` fenced 块（上游生成器自报清单），验证器只用一条稳定正则抓出该块、`yaml.safe_load` 成结构对象，再与 yaml1 旋钮按 `src 锚点[+sub]` 逐条 diff。**真双射**：yaml1 旋钮在块里找不到 = 幻觉/src 错；块条目在 yaml1 里找不到 = 漏译。报错精确到**年索引 + 两边值**。零人话解析、零脆性、零误报。
- **regex（回退）**：无 block 时，退回"按 src 定位 .md 小节 + 符号量级集合核对"。脆性见下。

**这套完全由块内容驱动，不含任何公司特定假设（兼容任意公司）。** 块的键是生成器自己的上挂科目锚点（= yaml1 的 `src`），生成器无需知道 yaml1 路径/defaults——尊重"生成器说人话、compiler 落路径"的分层。

### knobs 块格式（生成器吐、验证器读）

````
```knobs
horizon: [2025, 2026, 2027, 2028, 2029]
knobs:
  - {anchor: "#销售费用",   family: cost_rate, unit: pct,    values: [15.4, 15.4, 15.4, 15.4, 15.4]}
  - {anchor: "#整体毛利率", family: gpm,       unit: pct,    values: [29.2, 29.9, 30.5, 31.1, 31.6], override: true}
  - {anchor: "#资产处置收益", family: op_adj_abs, unit: abs_mn, values: [-70, -30, -30, -30, -30]}
  - {anchor: "#低温鲜奶", sub: 销量, family: factor_yoy, unit: pct, values: [7, 6, 6, 6, 6]}
  - {anchor: "#边缘业务", sub: 收入, family: growth,     unit: pct, values: [0, -10, -10, -10, -10]}
```
````

- `anchor` = 生成器上挂科目锚点，归一后须等于 yaml1 旋钮的 `src` 核心词。`sub` 区分一节多旋钮（销量/吨价/收入）。
- `unit`：`pct`（验证器 /100）/ `ratio` / `abs_mn`。值用**生成器显示惯例**（% 写百分数、金额写百万），验证器做单位归一后按**带符号**逐年比对。
- `override: true` 标主动覆盖项（值故意偏离外部模型，不去模型溯源）。
- 值用**满数组**（生成器把"全程/平推"自行展开），与 yaml1 等长逐年比。

验证记录（新乳业 002946，手抄块测试）：正确块 + 真 yaml1 → 23 PASS；正确块 + 注入 5 类错 yaml1 → C-DIFF/A/B 全抓、精确到年索引 → BLOCK。

## 边界（明确不做的）

- **不做语义级判断**：该不该有这条旋钮、判断是否成立、主动覆盖理由是否合理 —— Python 解决不了，是 compiler skill §9 人话回读和分析师的活。
- **block-diff 是逐年带符号精确比对**；regex 回退是集合核对（抓量级/符号/漏值，抓不了同小节纯顺序交换）。
- **完整漏译检测**：block-diff 下是严格双射；regex 回退下是近似（扫"含预测但无 src 认领的标题"）。

## 脆性现状

- **走 block-diff 时无脆性**——纯结构 diff，不解析人话。
- **走 regex 回退时**：可靠性 = .md 格式稳定性，格式漂移（措辞变、负号写法变、加粗丢失）会误报/漏报。

**根治路径已实现一半**：验证器侧的"有块用块、没块回退"已落地并测过（非破坏性，老 .md 照旧回退）。剩下一半是让上游 `核心假设生成器` skill 实际吐出 knobs 块——**这一步尚未做**（需改 `skills/核心假设生成修改器_skill_v17.md`），待决定后再动。届时生成器只需把已强制写出的精确逐年旋钮值，额外收拢成一个 fenced 块即可。
