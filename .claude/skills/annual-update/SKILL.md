---
name: annual-update
description: 把一家公司的旧核心假设.md 滚到最新年报。当用户说 "annual-update 新乳业"、"年度更新 某公司"、"把某公司核心假设滚到最新"、"某公司出年报了更新一下" 时使用。编排 init 刷数据 → 重建 defaults.yaml → annual_update_fetcher 取标准线 → 年度更新器 skill 滚旧稿(估算/重定/收口)。
argument-hint: [公司名或代码，如 新乳业 / 002946]
allowed-tools: Read, Grep, Glob, Edit, Write, Bash
---

# /annual-update — 年度更新编排

把一份**放旧的核心假设.md** 升级到**最新年报这一版**:数据自动滚到最新、标准线免费填、拿不到的非标原子和分析师一起估、未来按核心假设源语言的过表顺序被复盘分诊封顶地重定一遍。旧稿原样留存,另存带新日期的稿。

## 共享真源

滚稿阶段必须先加载：

```text
D:\MKA\skills\核心纪律_skill_v*.md
D:\MKA\skills\核心假设源语言_skill_v*.md
```

`/annual-update` 完整继承核心纪律 A1-A7，编辑同一套核心假设源语言 B。本文只保留年度更新独有条款：旧稿只读另存、外层 `/init` 刷数、声明式估算、双向核、annual_update_fetcher 取数清单。

## 定位(和 init / ka / comp 的边界,别混)

| 命令 | 做什么 | 不做什么 |
|---|---|---|
| `init` | 刷数据到 A(clean_annual) | 不碰核心假设.md |
| `ka` | 从材料生成/修改核心假设.md(通用) | 不管数据刷新 |
| `comp` | 核心假设.md → yaml1 → forecast | 不管数据/判断 |
| **`annual-update`** | **调用 init 刷数据/公告 + 重建 defaults.yaml + 把旧核心假设.md 从 H 滚到 A + comp 收口** | 不从零生成(那是 ka)、不重写 init 内部数据刷新逻辑 |

它用**年度更新器 skill v1** 的时间轴平移 + 声明式估算 + 收口报告,不是 `/adj incremental` 的通用补丁——`annual-update` 是"数据新了 N 年,把旧稿滚过去"的特定流程。

**边界一句话**:`/annual-update` 这个外层启动器会先调用 `python -m src.init <ticker>`,所以会复用 init 里的 TuShare 取数、年报/季报下载、Markdown 抽取、clean/reconciler、财务费用附注分析；init 成功后再调用 `py -m src.defaults_gen --ticker <ticker>`，把 `defaults.yaml` 的 `base_period` 滚到最新实际年。`skills/年度更新器_skill_v1.md` 只在数据刷新完成后接管"滚旧稿"阶段;它说"不拉数据"指的是滚稿阶段不再自己联网/抓公告,不是说 `/annual-update` 不跑 init。

## 触发

- "annual-update <公司>"、"年度更新 <公司>"、"把 <公司> 核心假设滚到最新"
- "<公司> 出年报了,更新一下核心假设"
- 给出公司名/裸代码/完整 ticker + 旧核心假设.md 已存在

**前提**:公司目录下已有 `*-核心假设.md`(否则不是更新,指 `/ka`)。

## 编排流程(5 步,前 3 步自动、第 4 步起人机交互)

### 第 1 步 · 读旧稿 + 读定调 + 建总账(自动,只读)

1. **定位公司目录**:`companies\{参数}_*` / `companies\*_{代码}`(同 /ka 第一动作)。
2. **读最新旧稿**:Glob 非递归 `companies\{公司}\核心假设*.md`(只认根目录,不认 `WEBCLADE\` 等子目录),取时间最新一份。从抬头提取:
   - **H(历史末年)**:抬头「历史 [起]-[止]」的止年。
   - 显式期 / 衰减期 / 永续点(第2步时间轴平移要用)。
   - 骨架(几条线、各什么族、毛利参数化、财务费用拆法、口径调整清单)。
3. **读定调**:`companies\{公司}\公司判断和最新观点.md`——分析师手写的 thesis,是第4步重定未来的判断锚点。**若它的日期明显旧于 H**(如定调是 2024.3、H 已到 2024),在进第4步前提醒分析师"定调旧了,这轮真实数据与 thesis 偏离点在 X,thesis 要不要先调"——thesis 调整是分析师的脑力活,本 skill 不替他做、不覆写该文件,只提示。
4. **建总账**:把旧稿里所有有历史序列的行列成清单(收入各线、毛利、各费用、below-OP 各项、税率、少数股东、派生观测行、收纳区副拆分、knobs 块、抬头四数)。后面逐项认领、划掉;收口时未划掉项 = 错或旗。
5. **识别按需扩展字段**:扫旧稿,凡有历史序列、但 fetcher 默认 19 条未覆盖的行(典型 BS 科目:营运资本/资本开支/存货/应收应付/有息负债;行业特有指标),记下它们的 TuShare 字段名(映射查 `src/field_registry.yaml`,见下「按需扩展」)。把这些字段名收集起来,第3步传给 fetcher。

没旧稿 → 报"无核心假设.md,这是 init 不是更新,请走 /ka",停。

### 第 2 步 · init 刷数据到 A + 重建 defaults(复用,后台跑)

```bash
python -m src.init <ticker>          # 增量,不带 --force
```

- 这是完整复用 init,不只是检查本地库:默认会跑 TuShare 增量取数、年报/季报下载、年报 Markdown 抽取、clean 配平、年报 reconciler 和财务费用附注分析。除非用户明确要求,不要加 `--no-markdown`/`--no-quarterly`。
- init 退出码为 `0` 后,立刻重建估值底座:
  ```bash
  py -m src.defaults_gen --ticker <ticker>
  ```
  这是年度更新的必要动作:如果 `clean_annual` 已到 2025,但 `defaults.yaml.base_period` 仍是 2024,`/comp` 和 `src.forecast` 的年份门禁会继续拦截正式 DCF。
- **复杂公司务必后台跑**(`run_in_background: true`,不接 `| tail`)——首跑几分钟到十几分钟,前台撞 10 分钟超时。init 逐行流式回显 clean/reconciler 日志,后台输出文件可 Read 看进度。轮询 reconciler 至少 sleep 300s(批量 LLM 静默期)。
- **退出码**:
  - `0` → 数据刷新成功,进第3步。
  - `3` → 年度硬校验失败(真数据问题)。**先走 init 的 subagent 升级通道**(派并发 subagent 啃残差,见 init SKILL「退出码 3」)。年度更新器**绝不在不可信数据上滚**——exit 3 未闭合就停,把残差给分析师,不进第3步。
  - `1/2` → 按 init SKILL 处理(报错 / websearch 兜底解析 ticker)。

### 第 3 步 · fetcher 取标准线 JSON(自动,确定性)

```bash
py -m src.annual_update_fetcher --ticker <ticker> --history-end <H> \
    --forecast-md "companies/{公司}/{旧稿核心假设}.md" \
    [--extra-fields "<字段1>,<字段2>,..."] [--out path.json]
```

- `--history-end H`:第1步从旧稿抬头提取的 H。
- `--extra-fields`:第1步识别的按需扩展字段(BS 科目等),逗号分隔,带点列名(如 `income.credit_impa_loss`)原样传。
- `--forecast-md`:旧稿核心假设.md 路径。顺带读末尾 knobs 块预测值,和真实值对比,产偏离诊断 md 到 `companies/{公司}/Agent/Logs/annual_update_deviation_{YYYYMMDD}_{A}.md`——**第4步人机交互的起点**(分析师扫表决定重拨哪些旋钮)。
- **输出 JSON**:`status` / `new_periods` / `lines.{标准线}.values.{年}` / `gaps`。
- **status 处理**:
  - `ok` → 拿 `lines` 进第4步。
  - `noop` → A==H,数据没新过旧稿,告诉用户"无需更新",结束。
  - `gap` → 守门失败(核心字段缺),把 `gaps` 给分析师指 `/init`,**不硬填、不静默用 0 顶替 NULL**,停。

### 第 4 步 · 年度更新器 skill v1 接管(人机交互 —— 这里开始不能全自动)

**先读偏离诊断 md**:第3步产出的 `companies/{公司}/Agent/Logs/annual_update_deviation_{YYYYMMDD}_{A}.md`(真实 vs 旧稿 knobs 预测对比)。它是第4步的起点——分析师扫表看哪些旋钮偏离大、thesis 兑现度,据此决定重拨范围。

**动态加载最新版 skill**:`skills\年度更新器_skill_v*.md` 中版本号最大的那一份(同 /comp 加载 compiler skill 的模式),Read 它,按其第2-5步执行:

- **第2步「标准线填历史」(自动)**:用第3步的 JSON `lines` 把 (H, A] 实际值 append 进旧稿各段:
  - 费用率/税率/比率类是 ratio(0.1556)→ 写进 .md 转百分比显示(15.56%)。
  - 绝对值原样搬,符号不翻(clean_annual 已是"对利润正负贡献"口径)。
  - fetcher 默认 19 条 + `--extra-fields` 的按需行,全覆盖。抬头时间轴四数 +N 平移;knobs 块 horizon 前移 N、values 前移(末年留空交第4步)。
- **第3步「估算拿不到的」(和你一起)**:非标业务线原子(销量/吨价/分线收入)走口径阶梯——
  - 分线收入:年报萃取 `收集\年报萃取\{年}_年报萃取.md` 分部表(若该公司没萃取文件,啃 `公告\年报\{年}_年度报告.md`)。注意旧稿分线口径可能与年报不同(如新乳业 4 线 vs 年报 3 类),按旧稿口径对齐,结构性残差推算可继续用。
  - 量价原子(销量/吨价):A 股年报不披露,外部模型 `active_vore\*.xlsm` 若未更新到 A 年 → 走**声明式估算·预测真实化**(旧稿对该年预测按比例缩放对齐真实营收)。标"估算·待校准"。
  - 先押再问,拍板才落盘。
- **第4步「重定未来」(和你一起)**:照核心假设源语言 B 的过表顺序(收入→毛利→费用→below-OP/税→中期),被复盘分诊封顶,以定调 thesis 为锚。每块只在"该重看"的行停,干净的平移带过。
- **来源冲突**:若旧稿、真实值、定调 thesis、偏离诊断或估算来源之间冲突,按核心纪律 A2 与源语言 B7 写“来源与裁决”(候选A/候选B/采用/未采用方去处),不能静默丢掉未采用方。
- **第5步「收口」(自动)**:跑 `/comp` → fidelity(block-diff 对新 knobs 块)→ forecast → DCF。完整性终检(总账每项划掉、新稿 ⊇ 旧稿)。出收口报告。**旧稿 + 旧 yaml1 原样留存**,另存带新日期的稿。

### 第 5 步 · 汇报

一页收口报告:滚了几年 H→A / 自动填的标准线(19+条)/ 按需扩展取到的 BS 行 / 估算了的(每条+方法+待校准)/ 挂旗待补的 / 重定了的(老值→新值)/ thesis 兑现度 / 新 DCF vs 平推 vs 旧稿 / 新稿路径+旧稿留存路径。

## 按需扩展:旧稿有、默认 19 条没覆盖的行去哪找(通用逻辑)

fetcher 默认 19 条覆盖**所有公司都有的 IS 通用标准线**:revenue_headline / 4 个费用率 / 8 个 below-OP 绝对值 / 有效税率 / 其他财务费用 / gpm 历史 / 少数股东比率 / 财务费用合计 / 5 个派生观测行 + 归母净利率。

但有些公司的核心假设.md 带资产负债表/现金流表科目(营运资本周转、资本开支、存货/应收应付周转、大额少数股东、有息负债结构、折旧政策)或行业特有指标(产能、门店数、用户数、ARPU)。**这些不可能每次都预输出**——按需找:

1. **识别**:第1步扫旧稿,凡有历史序列、但 19 条没覆盖的行,记下它的"上挂"中文科目。
2. **映射到 TuShare 字段名**:查 `src\field_registry.yaml`(全程序会计科目唯一真源,分类/会计序/标签)或 `数据格式参考.md`(中文科目 ↔ TuShare 字段名字典)。例:营运资本相关 → `total_cur_assets`/`total_cur_liab`;资本开支 → `c_pay_acq_const_fiolta`;存货 → `inventories`。
3. **传 fetcher 取**:`--extra-fields "total_cur_assets,c_pay_acq_const_fiolta"`。fetcher 按 direct 取,core=False 不阻塞(缺值挂旗不卡流程)。输出在 `lines.extra:<字段名>`。
4. **比率类(周转率/占比)skill 自己算**:fetcher 只取绝对值原子(搬运历史事实,非预测派生);周转率 = 字段/revenue 这种除法,skill 拿到分子分母后自己算,不算"算账"(和费用率同性质,历史实际比率)。
5. **映射查不到 → 挂旗待补**,不静默留空、不编字段名。

> 这条是通用性逃生通道:fetcher 不预知每家公司的特有行,但给 skill 一个"按字段名去 clean_annual 找"的确定入口 + 字段映射的权威来源。换任何公司,只要旧稿声明的行能映射到 TuShare 字段,就能滚。

## 纪律(必须遵守)

- **旧稿只读,绝不覆写**。永远另存带日期新稿(旧稿是复盘基准 + 后悔药)。
- **不在脏数据上滚**:init exit 3 未闭合 → 停,不进 fetcher、不滚旧稿。
- **绝不静默捏造**:拿不到的实际值只有两条合法出路——声明式估算(标"估算·待校准")或精确待补旗。禁止编数伪装实际、为配平倒算残差、改任何已知真实历史原子。
- **第4步起人机交互**:估算/重定是"先押再问、拍板才落盘",不能一口气跑完。这是 annual-update 和 init(全自动)的根本区别。
- **raw_tushare 永不被修改**;fetcher 只读 clean_annual,不写库。
- **定调文件只读当锚点 + 提示是否该刷新**,绝不覆写 `公司判断和最新观点.md`(那是 ka/分析师维护的)。
- **完整性**:旧稿每条线/历史/stash 只增不减;无新数据的线 carry + 标"无新数据·平移",绝不丢。靠总账 + 填或旗 + 有序走 + 双向核四条保证(→年度更新器 skill v1；总账纪律见核心纪律 A2)。
- 汇报用事实,不用营销词;估出来的要标"待校准"。

## 退出码 / 守门

| 阶段 | 失败 | 动作 |
|---|---|---|
| 第2步 init | exit 3 | 走 init subagent 升级通道;未闭合停,不滚 |
| 第3步 fetcher | status=gap | 把 gaps 给分析师指 /init,停 |
| 第3步 fetcher | status=noop | A==H 无需更新,正常结束 |
| 第4步 | 任何"填或旗"外的静默留空 | 总账未划掉项 = 错或旗,收口终检拦截 |
