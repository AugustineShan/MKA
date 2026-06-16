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

## 验证记录（新乳业 002946）

- 干净版：23 PASS / 0 FAIL → PASS（不误报）。
- 注入 5 类错（数组长度、嵌套错、符号反、销售费用率漏位、销量小数点滑位）→ 5/5 全抓 → BLOCK。

## 边界（明确不做的）

- **不做语义级判断**：该不该有这条旋钮、判断是否成立、主动覆盖理由是否合理 —— Python 解决不了，是 compiler skill §9 人话回读和分析师的活。
- **Gate C 是集合核对，不是逐年顺序核对**：抓量级/符号/漏值，抓不了同小节内的纯顺序交换（罕见）。
- **完整漏译检测是近似的**：反向扫"含预测但无 src 认领的标题"，非严格双射。

## 已知脆性与根治方向

Gate C 用正则读人话 `.md`，可靠性 = .md 格式稳定性。格式漂移（措辞变、负号写法变、加粗丢失）会导致误报或漏报。

**根治（可选加固，非当前必需）**：让上游 `核心假设生成器` 在 .md 末尾额外吐一个 fenced ` ```knobs ` 结构块（`path: [逐年值]  # src=...`），人话部分不动。Gate C 即可从"正则抠人话"退化成"读两个结构化清单逐条 diff"——零正则、无损。升级时让验证器"有块用块、没块回退正则"，平滑过渡，不破坏现有用法。
