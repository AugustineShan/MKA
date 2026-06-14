# 清洗yaml1.py — 设计文档 v1

> **它是理解层的 `clean.py`。** 吃一份非标的 `yaml1`(理解层的 raw_tushare)+ 一份 `yaml2`(defaults.yaml 平推基线),做完所有确定性的折叠 / 展开 / 再参数化落点 / resolve,吐出一份 **calc.py 能逐年消费的标准参数对象**,并用**历史回测**当闸。
>
> **它是纯确定性 Python,无 LLM。** LLM 的活已经在 compiler 干完了(yaml1 是 LLM 翻译的产物)。这一层只做机械的、可单测、可回测的变换。**失败时不调 LLM 补救,只举旗回人** —— 这是它和 `clean.py`(有 reconciler 补救)唯一的同构破口:翻译错回 compiler,数据错回 reconciler,但折叠/展开错只能回人改 yaml1 或 .md。
>
> **一句话职责:把"按线组织、含个性"的 yaml1,清洗成"按 yaml2 路径组织、逐年、引擎可直接吃"的标准参数,绝不丢信息、绝不算 DCF(DCF 是 calc.py 的事)。**

---

## 一、它在系统里的位置

```
核心假设.md ──[compiler·LLM]──> yaml1(非标·含 A 类覆盖 + B 类 stash)
                                   │
                    ┌──────────────┴───────────────┐
                    │                              │
          [清洗yaml1.py·Python]                  [前端]
          折叠 decomposition→revenue_yoy          读 stash(B 类)
          展开 flat / fade(hold/fade 分组)        不进 calc.py
          再参数化落点 / A·B 分离 / resolve⊕yaml2
          历史回测闸
                    │
          逐年标准参数对象(yaml2 同构,叶子=等长数组)
                    │
          [calc.py·纯 DCF 算账核·逐年驱动]──> 三表 + DCF
```

**同构表(焊在脑子里):**

| 数据层 | 理解层 |
|---|---|
| `raw_tushare`(EAV·非标) | `yaml1`(结构化·非标) |
| `clean.py`(透视+resolve+配平+reconciler) | **`清洗yaml1.py`(折叠+展开+resolve+回测闸)** |
| `clean_annual`(标准化·统一) | **逐年标准参数对象(yaml2 同构·逐年)** |

---

## 二、第一原则与边界

**做(全确定性):**
- 折叠 decomposition(量×价/增速 → 逐年营收 → 倒推 revenue_yoy 序列)
- 展开 flat / fade(按 hold/fade 分组)
- 把再参数化旋钮(gpm 等)摆到正确路径供 calc.py 逐年用
- A 类 / B 类分离(stash 不进参数表)
- resolve:yaml1 展开值 ⊕ yaml2 平推,逐路径合并
- 历史回测(硬,折叠/展开出的历史值复现 clean_annual)

**不做:**
- **不算 DCF / 不算三表 / 不配平 / 不解财务费用循环** —— 那是 calc.py 的算账核,一行不动。
- **不碰 stash 的内容**(只把它原样旁路给前端;不喂 calc.py)。
- **不发明数 / 不 plug 抹残差**(回测不过 → 举旗,绝不塞 plug 让它"假装平")。
- **不调 LLM**(失败回人)。

**铁律:** resolve 之后,参数对象里**每个 A 类叶子都是长度 = horizon 的数组**;标量(来自 yaml2 平推)在 resolve 时就广播成等长数组。**calc.py 进料口永远是数组,永不再判"标量还是数组"。**

---

## 三、输入 / 输出契约(贴着真实 calc.py)

### 3.1 输入

- `yaml1`(本公司,compiler 产物):A 类覆盖(knob 数组 / decomposition 子树 / 将来 formula)+ `terminal`(含 fade 的 hold/fade 分组)+ `stash`(B 类)+ `meta.horizon`。
- `yaml2`(defaults.yaml):平推基线,标量叶子,完整路径命名空间。
- `clean_annual`(本公司历史宽表):回测参照 + revenue base 锚 + 历史符号(复用昨天 `resolve_is_signs` 的成果)。

### 3.2 输出:逐年标准参数对象(`yaml2_yearly`)

**形态决策(已定):保持 yaml2 的嵌套结构,叶子从标量升级成等长数组。** 不做扁平表。

理由:calc.py 用 `get_path(y, "income.cost_rates.sell_exp")` 路径寻址取参。保持嵌套 → 逐年化改造**最小侵入**:取参点从 `as_float(get_path(...))` 改成 `get_path(...)[idx-1]`,寻址逻辑零改动;resolve(⊕ yaml2)就是同构树逐路径合并,最自然。

```yaml
# yaml2_yearly —— 清洗yaml1.py 的产物,calc.py 的输入
# 结构 = yaml2 完全同构;每个被逐年化的叶子 = 长度 horizon 的数组;
# 未被任何旋钮/逐年逻辑触及的叶子(如 market.*、balance_sheet.* 多数)= 仍是标量,calc.py 照旧读。
meta:
  horizon: [2025, 2026, 2027, 2028, 2029, 2030, 2031]   # + fade 展开后延到 2036(见 §5.3)
model:
  forecast_years: 12          # 7 显式 + 5 衰减(fade 展开后)
  revenue_yoy: [.., .., ..]   # ← decomposition 折叠倒推 + fade 段(数组,长度=forecast_years)
  terminal_growth: 0.025
  wacc: 0.08
income:
  gpm: [0.289, .., 0.305, 0.305, .., 0.305]    # 显式段逐年 + 衰减段 hold 30.5%
  effective_tax_rate: [0.1461, ..×12]
  minority_ratio: [0.0214, ..×12]
  cost_rates:
    sell_exp: [0.1545, .., 0.15, ..×到12]
    admin_exp: [..]
    rd_exp: [..]
    biz_tax_surchg: [..]
  cost_abs:
    assets_impair_loss: [-20, ..×12]
    # credit_impa_loss 等 yaml1 没碰的 → 取 yaml2 标量广播成 [..×12]
  operating_adjustments_abs:
    asset_disp_income: [-70, -30, ..×12]
    oth_income: [53.88, 40, ..×12]
    # forex_gain 等 → yaml2 广播
  below_line_abs:
    non_oper_income: [10.85, ..×12]
    non_oper_exp: [47.39, ..×12]
  financial_expense: { ... }   # ← 原样透传 yaml2(财务费用不在 yaml1,引擎倒算)
balance_sheet: { ... }         # ← 多数原样透传 yaml2(yaml1 未碰)
# stash 不在此对象内 —— 它旁路给前端
```

### 3.3 calc.py 侧改造(方案甲:逐年化那一刀)

**算账核一行不动,只改取参口。** 已核实的取参点(行号对 `calc.py`):

| 取参点 | 现状 | 改成 |
|---|---|---|
| `run_forecast` L357 `revenue_yoy` | `as_float`(标量,循环外读一次) | 循环内按 `idx` 取 `revenue_yoy[idx-1]` |
| `run_forecast` L360 `tax_rate` | `as_float` | 逐年 |
| `build_income_statement` L120-122 `gpm/tax/minority` | `as_float(get_path(...))` | 入参带 `idx`,取数组 `[idx-1]` |
| L125-128 `cost_rates/cost_abs/op_adj/below_line` (`value_map`) | 整段读成 `{字段:标量}` | `value_map` 升级成"取每个字段数组的 `[idx-1]`" |
| `build_balance_sheet` L192-196 `revenue_pct/cogs_days/capex_pct/...` | `value_map`/`as_float` | 同上(yaml1 没碰的仍是标量广播,机制统一) |

**绝不动的(跨年状态滚动链):** `run_forecast` 的 `for idx` 主循环、`prev_bs`/`prev_nwc`/`revenue` 的逐年滚存、`solve_forecast_year(prev_bs)` → `bs_row` 的依赖、`build_cash_flow` 现金桥、`validate_accounting` 配平、财务费用循环求解。**这些是 calc.py 的灵魂,逐年化只换"进料"不换"流水线"。**

**回归闸(calc.py 改造的验收):** 标量=flat 的退化情形必须逐字节回归——拿 yaml2 单独跑(不接 yaml1),把每个标量广播成等长数组喂进去,**5 家公司结果与现状逐字节一致**。证明"逐年化没破坏标量平推"。

---

## 四、六件确定性的活(主体逻辑)

### 4.1 decomposition 递归折叠 → revenue_yoy

**输入**:`income.revenue` 的 decomposition 子树(≤2 级,leaf 带 `revenue_family` + `base{base_year,...}` + `knobs`)。

**算法(后序遍历)**:
- **leaf · `vol_price`**:`收入_t = volume_t × price_t × 单位系数`;`volume_t = base.volume × Π(1+volume_yoy)`,`price_t` 同理。
  - ⚠️ **单位系数 honor yaml1 声明**:新乳 `base.volume` 万吨、`base.price` 元/吨 → `收入(百万元) = 销量 × 吨价 ÷ 100`。这个 `÷100` 从 `income.revenue.note` / stash caveat 读,**不 hardcode**;不同公司单位不同。
- **leaf · `growth`**:`收入_t = base.revenue × Π(1+revenue_yoy)`。
- **rollup 节点**:`收入_t = Σ children 收入_t`(递归;混合深度天然支持)。
- **顶层 `income.revenue`**:得到逐年营业收入总额序列 `R = [R_2025..R_2031]`。

**倒推 revenue_yoy(已定形态)**:
- `revenue_yoy[1] (2025) = R_2025 / clean_annual.revenue(2024 实际) − 1`
  ⚠️ **base 锚 clean_annual.revenue,不是四线 base 加总** —— 与 calc.py 的 `income.revenue` base 口径一致(都锚 clean_annual),避免四线加总那 0.15 精度差污染起算点。
- `revenue_yoy[t] = R_t / R_{t-1} − 1`(t≥2026)
- 覆盖 `model.revenue_yoy`(数组)。**calc.py 的 `revenue *= (1+revenue_yoy)` 收入引擎一行不改**,只是吃数组。

> decomposition 子树**不进** `yaml2_yearly`;它折叠成 revenue_yoy 后即"消费完毕"。原始子树连同 stash 一起旁路给前端(供 breakdown 展示)。**calc.py 永远看不到 decomposition。**

### 4.2 旋钮展开
yaml1 的 knob 已是满数组(compiler 在编译期摊好),这步只做**按 horizon 对齐 + 长度校验**(长度 ≠ horizon → 举旗)。

### 4.3 fade 展开(按 hold/fade 分组)
读 `terminal`:`explicit_end`、`fade{to_year, kind, fade_paths, hold_paths}`、`perpetual_growth`。
- **延长 horizon**:显式期(7 年,到 2031)+ 衰减期(`to_year` − `explicit_end` = 5 年,到 2036)→ `model.forecast_years = 12`。
- **`fade_paths`(如 `revenue`)**:从显式期末值(2031 的 revenue_yoy)**线性 fade** 到 `perpetual_growth`(2.5%),5 年逐年插值,接在 revenue_yoy 数组后面。
- **`hold_paths`(如 `income.gpm`)**:衰减期内**钉住显式期末值**(30.5%),数组后 5 年全填 30.5%。
- **未列入 fade/hold 的逐年路径**:默认行为需定 —— **我押"衰减期保持显式期末值(hold)"**,因为"未声明 fade 即不 fade"最安全(费用率、税率到 2031 就稳定了,衰减期不该自己漂)。⚠️ 这条写进文档当默认,但留一个 §决策点 给你确认。
- ⚠️ **`.md` 写了 hold/fade 分组但 terminal 没承载 → compiler 已该举旗**;清洗这层再校一次:`fade_paths`/`hold_paths` 引用的路径必须真实存在于参数对象,否则举旗。

### 4.4 再参数化落点
gpm 是手拍旋钮(yaml1 已声明)。清洗**不算营业成本**(那是 calc.py:`oper_cost = revenue×(1−gpm)`),只把 gpm 数组摆到 `income.gpm` 路径。**清洗只搬运参数化的"接线",不执行派生。** 若某公司在产品线级拨 margin(`vol_price_margin` 族),则折叠时连成本一起折(成本侧也倒推到对应路径)——按 yaml1 声明的族走,不 hardcode。

### 4.5 A / B 分离
- **A 类**(进 `yaml2_yearly`):decomposition(折叠后)、所有 income 路径 knob、terminal。
- **B 类**(旁路给前端,**不进参数对象**):整个 `stash`、以及 decomposition 原始子树(供 breakdown)。
- 边界:`stash` 内容**绝不**进 calc.py 任何路径;清洗只做"原样转交",不解析、不校验其数值(它是参考信息,不是计算输入)。

### 4.6 resolve ⊕ yaml2
**同构树逐路径合并**:
- yaml1 出现的 A 类路径 → 用 yaml1 展开后的逐年数组。
- yaml1 缺席的路径 → 取 yaml2 标量,**广播成长度 = forecast_years 的等长数组**。
- 产出 `yaml2_yearly`(§3.2):每个 A 类叶子等长数组,其余(yaml1 没碰、calc.py 也不逐年用的,如 `market.*`)原样透传标量。
- **financial_expense 永远走 yaml2**(财务费用不在 yaml1,引擎倒算)。

---

## 五、历史回测闸(信任的来源)

清洗不靠"它没出错"取信,靠**可回测**。回测分两轨(沿用上一轮定的"翻译忠实度 / 计算忠实度"切法,这一层管计算忠实度):

### 5.1 历史轨(硬闸,零妥协)
用 yaml1 的 base 原子 + 骨架,在**历史年份**上跑折叠,必须复现 `clean_annual` 的已知历史值:
- **分线**:`base.volume × base.price × 单位系数 ≈` 该线历史 headline(stash 里的分线收入序列)。
- **加总**:四线折叠 ≈ `clean_annual.revenue`(2024:四线和 10665.5 ≈ headline 10665.42,容差内)。
- **符号**:减值等易翻符号项,复用昨天 `clean.py` 的 `resolve_is_signs()` —— **逐年按实际符号**,不假设恒负;2019 前口径断点降级为 warning,不阻断(和昨天定的一致)。
- 不过 → 说明 base 原子 / 族 / 单位系数 / 折叠逻辑错 → **举旗回人**(改 yaml1 或 .md),不猜、不 plug。

### 5.2 预测轨(软闸,仅"照搬券商"线)
只对标了"老板认券商模型"的线:折叠出的预测 ≈ 券商模型预测。
- **主动覆盖线豁免**(gpm 翻转、营业外支出修正、税率维持)—— 它们故意 ≠ 券商,回测无意义;这些线的真值裁判是 compiler 收尾的"主动覆盖线人话回读"(已在 compiler skill §9),不在这一层。

### 5.3 闸的纪律
- **判定离散对错(复现/不复现),绝不制造连续残差去填。** 不过就举旗,不 plug。
- 这与 `clean.py` 的配平校验同性质:用一条可信参照(clean_annual / 券商历史),把"折叠对没"变成客观判定。

---

## 六、失败处理(绝不静默)

| 情形 | 动作 |
|---|---|
| 旋钮数组长度 ≠ horizon | 举旗,报哪条路径 |
| decomposition 深度 > 2 / rollup-leaf 混淆 | 举旗(compiler 本该拦,这层再防一道) |
| 单位系数缺失(note 没声明 ÷ 系数) | 举旗,不默认 ÷100(不同公司不同) |
| fade_paths/hold_paths 引用了不存在的路径 | 举旗 |
| 历史轨回测不复现 | 举旗回人改 yaml1/.md;**不 plug、不调 LLM** |
| yaml1 某 A 类路径在 yaml2 里查无(resolver 无处可盖) | 举旗(可能 compiler 漏标 unaligned) |

**所有失败一律举旗 + 定位 + 回人。** 这一层没有 reconciler、没有 LLM 补救 —— LLM 的活在 compiler 已干完,这里只准确定性变换。

---

## 七、模块结构建议(供 Claude Code,intent 级,不锁实现)

> 给 agent 的是 intent + 约束 + 闭合条件,**让它先读 calc.py / yaml2_schema 现状、出设计提案,确认后再写**。不要在这份文档里锁死函数名/签名。

意图分解(逻辑阶段,不强制对应文件):
1. **fold**:decomposition → 逐年营收 → revenue_yoy(§4.1)
2. **expand**:旋钮对齐 + fade 展开(§4.2/4.3)
3. **resolve**:⊕ yaml2 → yaml2_yearly(§4.6)
4. **backtest**:历史轨硬闸 + 预测轨软闸(§五)
5. **calc.py 逐年化**:取参口标量→数组(§3.3),算账核不动,回归闸守

**闭合条件(新乳端到端)**:`核心假设.md → compiler → yaml1 → 清洗yaml1.py → calc.py → DCF` 跑通,且:
- 历史轨回测全过(四线折叠复现 clean_annual);
- calc.py 标量回归闸 5 家逐字节一致;
- 新乳 DCF 用 yaml1(gpm/税率数组覆盖)跑出每股价值,无断链、配平不崩。

---

## 八、与算法模式的接口(留槽,不实现)

将来 yaml1 出现 `formula` 节点(茅台基酒链那种),清洗的 **fold 阶段按 `kind` 分派**:今天折 decomposition,将来求值 formula DAG(拓扑序 + 年份滞后序,沙箱受限表达式)。**两者归宿相同**(都折成 revenue_yoy 等标准参数)、**消费者相同**(清洗自己)、**对 calc.py 都不可见**。所以今天 fold 阶段就按"按 kind 分派"写,formula 分支留空举旗("算法模式求值器未实现"),**等茅台级公司逼出来再建求值器**,结构不重写。

---

## 一句话

**`清洗yaml1.py` 是理解层的 clean.py:把非标 yaml1 折叠(decomposition→revenue_yoy,honor 单位系数)、展开(flat + fade 的 hold/fade 分组)、再参数化落点、A/B 分离、resolve⊕yaml2,吐出一份 yaml2 同构、叶子等长数组的逐年参数对象;calc.py 只把取参口从标量升级成按年索引、算账核一行不动;历史回测当硬闸,失败举旗回人、绝不 plug 绝不调 LLM。它让 compiler→yaml1→清洗→calc.py 这条链闭合,新乳第一次端到端跑出 DCF。**
