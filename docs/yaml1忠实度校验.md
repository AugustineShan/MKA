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

## 减值符号门 + top-level knob sub 兜底（2026-06-30）

两道独立于 block-diff 的硬门，补 block-diff 自身盲区：

- **减值符号门（`IMPACT_SIGN`）**：`cost_abs` 减值三字段（`assets_impair_loss`/`credit_impa_loss`/`oth_impair_loss_assets`，集合在 `src/impact_fields.py` 的 `IMPACT_ADJUSTMENT_FIELDS`）是带符号损益调整，引擎 `calc.py` 以 `+impact_adjustment` 并入 operate_profit。yaml1 中这三个 path 叶子若存严格正数 → FAIL。零放行（百润 assets_impair=0 等合法）。**为何需要**：block-diff 是"yaml1 vs .md knobs 块"逐值比对——若 .md 作者误写正数幅度（"损失项写正数金额"惯例）且 compiler 照抄正数，block-diff 两边都正会判 PASS，但引擎会把正数当加项加回、静默虚增利润。此门按 path 叶子名（TuShare 字段名）精确判定，不依赖中文 anchor 映射，无误报。存量公司 cost_abs 全为负/零，不破坏。
- **top-level knob sub 兜底**：block-diff 对 top-level `kind: knob` 原本只按 `(anchor, None)` 查 knobs 块；若块条目带 `sub`（如 `balance_sheet.dividend_payout` ↔ `{anchor:#分红率, sub:dividend_payout}`）则匹配不上、误报"幻觉"。现在 `lookup(anchor, None)` 未命中时，用 yaml1 path 叶子名（`dividend_payout`）作为 sub 再查一次。复用现有 `lookup` 闭包 + `_SUB_ALIAS`，不改 `collect_knobs` 签名。

配套：`.md` 侧 `ka_assumption_lint.py` 加 `COST_ABS_SIGN` 门（`family==cost_abs` 且正值 → FAIL），在 /ka 落盘时早拦，根本不到 /comp。`/ka` skill 已把 `ka_assumption_lint` 接成 official 稿落盘后必跑闸。符号约定单一真源在 `docs/knobs块契约.md` §7 family 表"符号"列 + `skills/yaml1compiler_v5.md` 附录A 减值符号结论。

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

### knobs 块格式

格式细则以 `docs/knobs块契约.md` 为单一真源。这里仅记录校验器消费侧的关键点：

- fenced block 第一行规范写 ` ```knobs`。
- 块内是 YAML；顶层 `knobs` 是数组。
- 每条用 `anchor` 和可选 `sub` 与 yaml1 的 `src` / revenue leaf 输入相连。
- `unit: pct` 会先除以 100，再与 yaml1 小数比；`ratio` / `abs_mn` 原样比。
- `values` 必须是满数组，并与 yaml1 显式 horizon 等长逐年比。
- `yaml1` 有而块里没有 = 幻觉或 src 错；块里有而 `yaml1` 没有 = 漏译或多写派生输入。

验证记录（新乳业 002946，手抄块测试）：正确块 + 真 yaml1 → 23 PASS；正确块 + 注入 5 类错 yaml1 → C-DIFF/A/B 全抓、精确到年索引 → BLOCK。

## 边界（明确不做的）

- **不做语义级判断**：该不该有这条旋钮、判断是否成立、主动覆盖理由是否合理 —— Python 解决不了，是 compiler skill §9 人话回读和分析师的活。
- **block-diff 是逐年带符号精确比对**；regex 回退是集合核对（抓量级/符号/漏值，抓不了同小节纯顺序交换）。
- **完整漏译检测**：block-diff 下是严格双射；regex 回退下是近似（扫"含预测但无 src 认领的标题"）。

## 脆性现状

- **走 block-diff 时无脆性**——纯结构 diff，不解析人话。
- **走 regex 回退时**：可靠性 = .md 格式稳定性，格式漂移（措辞变、负号写法变、加粗丢失）会误报/漏报。

**当前状态**：验证器侧的"有块用块、没块回退"已落地；上游核心假设源语言也已把末尾 ```knobs 机器自报清单纳入正式契约。当前 `/ka`、`/load`、`/adj incremental`、`/annual-update` 产出的正式核心假设都应尽量带 knobs 块；`/adj quick` 和 `/frontend-edit` 修改时必须同步正文与 knobs。老 `.md` 没有 knobs 块时仍走 regex 回退，但这只作为兼容路径，不应作为新产物标准。
