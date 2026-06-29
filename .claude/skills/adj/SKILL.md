---
name: adj
description: 启动 ADJ 核心假设调整器。支持 quick：只拨动已有 knobs，确认 patch plan 后回写核心假设.md、定点 patch yaml1 并跑 DCF；支持 incremental：先 markdown 化 ADJ 增量材料，再按补丁尺度修改核心假设源文，最后走 /comp。
argument-hint: [公司名或代码 + 调整请求，如 新乳业 把毛利率稍微提一提 / 新乳业 增量]
allowed-tools: Read, Grep, Glob, Edit, Write, Bash
---

# /adj - 核心假设调整器

`/adj` 专职做正式核心假设的调整，不回到旧 KA 局部修改模式。

```text
quick       = 用户一句话小改 -> 确认是已有 knobs -> patch 核心假设.md + patch yaml1 -> forecast
incremental = 读取 ADJ 增量材料 -> 讨论系统性影响 -> 修改核心假设.md -> /comp -> forecast
```

## 0. 共享真源

执行前加载：

```text
D:\MKA\skills\核心纪律_skill_v*.md
D:\MKA\skills\核心假设源语言_skill_v*.md
```

`/adj incremental` 按补丁尺度继承核心纪律 A1-A7，编辑同一套核心假设源语言 B。`/adj quick` 只继承 A1/A3/A6/A7 的定点回写形态，不做研究判断。

`/adj quick` 允许 direct yaml1 patch 的唯一理由和边界见核心纪律 A4：白名单不可加宽；`核心假设.md` 是 canonical，yaml1 是派生缓存；三处不同源时 md 赢，回到 `/comp`，不得继续手 patch yaml1 去凑一致。

交互风格继承核心纪律 A4：`quick` 给用户看“手术单”，`incremental` 给用户看“增量影响 memo”。先说你理解要改什么、为什么只是小改或为什么需要增量流程，再等确认；不要把 knobs/yaml1 清单机械倾倒给用户。

## 1. 解析公司与模式

从 `$ARGUMENTS` 定位 `D:\MKA\companies\{公司}`。

模式判断（单一决策树，关键词仅作提示信号不作判据）：

1. 请求能否**语义映射**到已有 knobs 的 `values[i]`（或 `terminal.perpetual_growth` 标量）？
   - 能 + 不碰结构/horizon/fade → **quick**。
   - 不能，或带了新业务理由/新材料/结构变化（“新开渠道”“竞争格局变了”“管理层目标变化”等）→ **incremental**。
2. 关键词“增量/读材料/ADJ材料/新信息/边际信息”只是 incremental 的提示信号；命中不强制 incremental，不命中也不强制 quick——以第 1 步语义映射为准。
3. 映射不到且无新业务理由 → 不猜，列出可拨 knobs，问是否调整最接近的 knob，或建议 incremental。

## 2. 共同前置读取

两种模式都先定位：

- 同权重判断材料：先运行 `py -m src.ka_prepare "{公司}"`，读取同权重 `markdown存储区/` 与 manifest；其中 `公司判断和最新观点.md` + `重要文件\` 顶层材料同等权重，凡读公司判断必须一起读。
- 公司根目录最新正式 `*核心假设*.md`。
- `Agent/` 下最新 `yaml1_*.yaml`。
- `Agent/defaults.yaml`。
- `Agent/data.db`。
- 当前 `Agent/forecast/dcf_summary.json`，若存在。

缺 `公司判断和最新观点.md`、`ka_prepare` 失败、缺正式核心假设或 yaml1 时停止。`/adj` 调整的是已有正式稿，不负责从零生成。manifest 中 `unsupported/error` 必须进入缺口区；quick 模式若同权重判断材料与用户小改方向冲突，先提示再让用户确认是否仍执行。

## 3. quick 模式

quick 只能做已有 knobs 的数值小改。

**quick 可拨旋钮白名单 + 禁止清单 + 结构判定的单一真源是 `docs/旋钮白名单与结构判定.md`**（§一白名单、§二禁止、§三结构判定表）。本启动器不重抄，只守其约束：白名单不可加宽；任何新增 path、改结构、改 slug、改 family、改 horizon 或 fade 的请求都转 `/adj incremental` 或 `/comp`；结构改动走 §三判定表，不用"参数化翻转/推翻裁决基础"等主观词。

quick 允许的动作：

- 只拨动已经存在的 knobs 数值（须落在白名单内）。
- 修改 `核心假设.md` 正文预测行 + 末尾 `knobs` 块。
- 定点 patch 最新 yaml1 中对应已有 path / values。
- 跑 `py -m src.forecast --yaml1 "<今日yaml1>"`。
  - **(audit R6/H2a)** official forecast 现在会自动跑 yaml1 结构/路径保真闸门:若 quick patch 不慎越界(改了 family/结构/path、偏离 defaults 命名空间),Gate A/B 会 FAIL 并阻断 forecast(exit 4),逼你回 `/comp`——quick 不再能静默把结构性改动送进 DCF。确需临时放行设 `MKA_FIDELITY_GATE=warn`。

`knobs` 块语法以 `docs/knobs块契约.md` 为准；quick 只改已有条目的 `values[i]`，不改块结构。

若用户请求不是已有 knobs 数值调整，返回：

```text
这个不能在 quick 模式直接拨。它不是已有 knobs 的数值调整。
我可以改这些已有 knobs：{列出可拨旋钮}。
如果要新增结构/改参数化，请走 /adj incremental。
```

quick 执行：

1. 读取核心假设末尾 `knobs` 块与 yaml1。
2. 从自然语言生成 patch plan：knob、年份、old -> new、单位、yaml1 path。
3. 先和用户确认 patch plan；未确认不落盘。
4. 归档旧核心假设。
5. 写今日新核心假设到根目录。
6. 定点 patch 今日 yaml1。
7. 三处同源核对：正文、`knobs`、yaml1。
8. 跑 forecast 并汇报 per-share value。

patch plan 聊天格式要像手术单：

```text
我理解这是一个 quick 小改，只动已有旋钮：
| 旋钮 | 年份 | 旧值 | 新值 | 影响 |

不会改：结构、历史、来源、horizon、yaml1 path。
确认后我归档旧稿，写今日新稿，定点 patch yaml1，并跑 forecast。
```

三处不同源时停止，不跑 forecast。tie-break：`核心假设.md` 赢，yaml1 视为派生缓存，回到 `/comp` 重编译。

## 4. incremental 模式

incremental 用来处理新材料、新业务信息、新边际变化。它不是快改 yaml1。

素材入口：

```text
companies\{公司}\Skills素材包\ADJ增量信息（用来改模型的边际信息）\
```

先运行：

```bash
py -m src.adj_prepare "{公司}"
```

AI 只读：

```text
companies\{公司}\Skills素材包\ADJ增量信息（用来改模型的边际信息）\markdown存储区\
```

执行顺序：

1. 读取同权重判断材料、当前正式核心假设、最新 yaml1、当前 DCF。
2. 跑 `src.adj_prepare`，读 ADJ markdown 存储区。
3. 加载最新 `D:\MKA\skills\核心假设调整器_skill_v*.md`。
4. 识别增量信息影响哪些假设：收入、毛利/成本、费用、below-OP 与税、中期/terminal。
5. 形成“受影响假设清单”和“建议调整方案”，先和用户讨论。
6. 用户拍板后，只修改核心假设源文，不直接改 yaml1。
7. 调用 `/comp` 纪律重新编译 yaml1，再跑 DCF。

讨论格式用增量影响 memo：

```text
我读完增量材料后，判断它影响这些地方：
| 假设 | 旧稿怎么写 | 新信息怎么改变 | 我建议 |

需要你拍板：
- ...

这个调整范围可以吗？确认后我只改这些受影响行，再走 /comp。
```

若增量材料与旧正式稿或其它来源冲突，按核心纪律 A2 与源语言 B7 写“来源与裁决”，不能静默丢掉未采用方。

incremental 本地纪律：

- 只读同权重判断材料、现有正式稿和 ADJ markdown，不通读其它材料。
- 改动清单必须写：哪行、哪年、从 X 到 Y、为什么、哪来的。
- 级联不静默：改原子时 headline/加总/knobs 同步过。
- 结构改动按 `docs/旋钮白名单与结构判定.md` §三判定表处理：新增/删除线、改参数化族、改 horizon/fade → incremental 开骨架门、列连带清单；thesis 方向反转 → 弹回 `/ka 重建`，不硬补丁。
- manifest 的 `unsupported/error` 必须进入缺口。

## 5. 汇报

quick 汇报：

- knob / 年份 / old -> new。
- 核心假设新文件路径。
- yaml1 新文件路径。
- 三处同源核对是否通过。
- DCF 每股价值与 forecast 路径。

incremental 汇报：

- 已读 ADJ markdown 材料。
- 受影响假设清单。
- 用户拍板的改动。
- 新核心假设路径。
- `/comp` 生成的新 yaml1 路径。
- DCF 每股价值与 forecast 路径。
