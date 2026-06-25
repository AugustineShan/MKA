# da 折旧摊销排程 skill v1 — 执行细则

> 动态加载的 runbook。设计权威是 `docs/superpowers/specs/2026-06-24-da-skill-design.md`(§3 并行事实抽取 / §4 商议协议 / §5 落盘收口 / §6 da_roll / §12.2 schema / §12.3 输出);本文件是操作落地,不重新推导设计。由 `/da` launcher(`.claude/skills/da/SKILL.md`)按 `da_折旧摊销排程_skill_v*.md` glob 加载。
>
**定位**:`/da` 是"事实抽取 + 假设商议"编排器,不是计算器。计算永远归 Python(`src/da_roll.py`)。skill 全部内容围绕"怎么把年报里人啃不动的东西读干净,再怎么和分析师商议出未来假设"展开。

## 三阶段流程

```
第一阶段:并行事实抽取 → Agent/recon/da_facts_latest.json   (事实层,LLM 扒)
第二阶段:商议协议       → Agent/da_schedule.yaml            (假设层,先押再问拍板才落盘)
第三阶段:落盘与收口     → 重跑 src.forecast 触发重资产 DCF
```

---

## 第一阶段:并行事实抽取 → `Agent/recon/da_facts_latest.json`

**已实现**:`src/da_facts.py`。直接调 CLI,不要手写抽取逻辑。

```bash
py -m src.da_facts --ticker {代码} --base-year {base_year} --years 5
```

### 编排规则(已实现,这里说明边界)

- **并行维度**:按"附注类型 × 年份"铺 subagent,每个窄上下文单一目标——固定资产明细表 × 近 5 年、在建工程明细表 × 近 5 年、无形资产明细表 × 近 5 年、会计政策年限残值率表 × 最新年。**生产性生物资产 / 油气资产明细表 + 政策段为可选维度**:年报披露了就抽(`depr_fa_coga_dpba` = 固定资产折旧 + 油气资产折耗 + 生产性生物资产折旧,三类同源,缺一类就让 scale 偶然、每类归因错),没披露(非乳业/非油气公司)→ `not_disclosed` 静默跳过,不触发理智闸门。声明式驱动披露有无,不写死"乳业必加"。
- **抽取契约**:给定 schema,**只填表不推算**。抽不到 → 留 `null` 标 `missing`,**绝不补零**(补零 = 静默造假,与项目第一原则同构:reconciler 不静默吞错,da_facts 不静默凑数)。
- **schema 守卫**:`extract_note` 的 `allowed_fields` 白名单剥掉 LLM 编造的 schema 外字段(借鉴 reconciler 三层防脏)。`validate_da_facts` 校验 `0` 值必须配 `missing_flag`,否则报错。
- **roll-forward 闭合自校验**:`check_rollforward` 逐年逐类验 `期初净值 + 本期增加 − 本期折旧 − 本期减少 − 减值 = 期末净值`,残差 < 1(百万元,与 clean.py 硬校验容差对齐)才 `closed: true`。不闭合写进 `da_facts.json.roll_forward_checks`,**不静默放行**。
- **每个数字带 `source_year` + 附注锚点**(md 行号/章节),写进 `evidence_anchors`。可追溯。

### 复用基础设施(已接好)

- `call_llm`(`annual_report_utils.py`)+ GLM `glm-5.2` `thinking:disabled`(防烧 reasoning token 截断)。
- `parallel_map`(并发,fallback 降 3,429 退避 30/60/90s)。
- `find_line` / `compact_window` / `find_all_lines`(年报 md 切片定位)。
- `annual_markdown_path`(年报路径查找,缺则 `python -m src.report_downloader --ticker {t} --force-markdown`)。
- `known_tushare_defects.json` 提示卡(只在需要定位附注时作线索,不是补丁库)。

### 产物纯净

`da_facts_latest.json` **只装事实,不装假设**。年限/残值率/原值/累计折旧/本期增减都是年报披露的客观值。任何"未来"的东西(扩张计划、转固节奏、终值 ratio)不进 da_facts,留到第二阶段商议。

时间戳副本同时落 `Agent\recon\da_facts_YYYYMMDD_HHMMSS.json` + `da_facts_latest.json`。

---

## 第二阶段:商议协议 → `Agent/da_schedule.yaml`(灵魂)

### §4.1 先押再问

读 `da_facts_latest.json` 后,**先基于历史结构提一版完整默认假设**(选型 + 预测值 + 理由 + 来源),再逐项征求分析师确认。不是空问"你想怎么设",而是"我看历史是这样,我建议这样,你改不改"。

### §4.2 拍板才落盘

分析师确认前**不写** `da_schedule.yaml`。每一项用户拍板后才落盘。**禁止未拍板落盘。**

### §4.3 capex 商议六点(按序,必须六点全覆盖)

1. **摆事实定基线**:先报客观情况——过去 5 年 capex 多少、capex/收入比区间、capex/D&A 比区间、在建工程余额趋势、capex 是平滑还是阶梯状。共同事实基础。
2. **维持性 capex(确认而非商议)**:取 `da_roll` 的存量稳态折旧(base 水平,`stock_depreciation`)。派生项,分析师点头即可,不纠结。FCFF 里与存量折旧对冲净 0(见 spec §6.2)。
3. **扩张性 capex(真商议焦点)**:把分析师脑里的产能 thesis 翻译成排程。
   - 有没有管理层指引?先报从年报/纪要读到的管理层 capex 计划数(若有),问信不信、用不用。有指引时最强先验。
   - 未来扩张的实物计划?"未来三年新增多少产能?建几个牧场/几条产线/多少万吨?"——人话,分析师回答核心。
   - 单位投资额?从历史在建工程单位成本估,分析师校准。
   - 节奏?分几年投、哪年多。决定 `expansion_plan[year].capex_by_cat` 逐年形状。
4. **转固时滞(capex→未来折旧的桥)**:"这些扩张投资哪年完工转固、开始计提折旧?"明确确认 `cip_to_fixed` 节奏。**今天投的 growth_capex 趴在 cip 不折旧,转固那年才起跳**。漏了这一问 capex 和 DA 脱钩,重资产模型白做。对应 `expansion_plan[year].cip_to_fixed` + `base_cip_to_fixed`(存量 cip 的已承诺转固)。
5. **终值稳态假设**:"长期看稳态时 capex 大概是 D&A 的几倍?"通常成熟期回到 `capex_da_ratio≈1`(只维持)。决定显式期后终值怎么接,交接点 FCFF 不跳变。对应 `terminal.capex_da_ratio` + `terminal.perpetual_growth`。
6. **存量净增率 g override(§6.4 存量永续更新)**:默认 `net_growth_rate: 0.0`(永续更新,存量净值/折旧维持 base 水平不熔)。若分析师给存量逐年净增率 `g`:`net 增率同时作用于存量净值与存量折旧`——两者都按 `(1+g)^t` 涨。**不允许只涨基数不涨折旧**(基数与折旧脱钩 = 静默不一致)。`g>0` 必须配有机增长 capex(`da_roll.organic_capex` 自动补 `g × 存量_net`,否则 BS/CF 静默失衡);`g=0` 模型现金自洽(维持 capex=存量折旧、存量净值走平)。

### §4.4 诚实于不确定(贯穿全程)

拿不到的值只有两条合法出路,不准 LLM 编:
1. "声明式估算·待校准"——给一个带理由的初值,标 `待校准`,提示这是模型最大敏感点。
2. "待补旗"——留 null,标 `待补旗`,后续补。

押要带理由+来源,用户可驳。不假装确定。

### da_schedule.yaml schema(spec §12.2,loader 已实现)

```yaml
enabled: true                      # true 才被 forecast.py 消费
base_year: 2024                    # 必须 = defaults.base_period 的年份(load_da_schedule 校验,不匹配 DaAlignError)
generated_at: ...

ppe:
  存量策略:
    mode: perpetual_renewal        # 默认永续更新(存量不折尽,见 spec §6.2)
    net_growth_rate: 0.0           # 存量逐年净增率,默认 0(稳态);§4.3 第六点
  categories:                      # 分类别 cohort
    - {name: 房屋及建筑物, life_years: 20, salvage_rate: 0.05, base_gross: .., base_accum_dep: .., base_cip: ..}
    - {name: 机器设备,     life_years: 10, salvage_rate: 0.05, base_gross: .., base_accum_dep: .., base_cip: ..}

base_cip_to_fixed:                 # base 年既有在建工程的转固排程(da_facts.cip_detail 存量 cip,已存在承诺)
  2025: {机器设备: 80000, 房屋及建筑物: 120000}    # 这批存量 cip 转固起折旧
  2026: {房屋及建筑物: 60000}
  # 不变量:累计 base_cip_to_fixed ≤ base 年 cip 余额(da_facts);da_roll.CipInvariantError 强制

# other_depreciating_assets(可选):也折旧但非 PP&E 的资产类——生产性生物资产(奶牛)/油气资产。
# depr_fa_coga_dpba 是三类折旧同源;只建模 PP&E 会让生物/油气折旧被吸进 PP&E scale(偶然对齐、
# 每类归因错、轨迹耦合)。披露了就声明,让 da_roll 把它们纳入折旧流量 + 稳态再投资(=其折旧,
# 堵 FCFF 陷阱),净值不进 fix_assets(BS held flat = 稳态,reinvest=折旧,自洽)。
# v1 稳态(g=0,无扩张 cohort);生物资产扩张(牛群扩大)是未来可加项(走 cohort + BS 路由)。
other_depreciating_assets:
  存量策略:
    net_growth_rate: 0.0           # 默认 0 稳态(净值平推);>0 则存量折旧按 g 涨
  categories:                      # 从 da_facts.prod_bio_detail / oil_gas_detail + policy 取
    - {name: 生产性生物资产, life_years: 5, salvage_rate: 0.20, base_gross: 1360.099, base_accum_dep: 290.367}
    # base_gross/life/salvage 驱动 policy_dep(参与 scale 分母);base_accum_dep 仅记录,不进 fix_assets_net

expansion_plan:                    # 分析师商议的新增扩张 capex 排程(§4.3 第三点)
  2025:
    capex_by_cat: {机器设备: 50000, 房屋及建筑物: 200000}
    cip_to_fixed: {机器设备: 30000}                 # 当年转固(§4.3 第四点)
  2026:
    capex_by_cat: {房屋及建筑物: 300000}
    cip_to_fixed: {房屋及建筑物: 200000, 机器设备: 20000}
  # 不变量:任一年任一类 累计 cip_to_fixed ≤ 累计 capex_by_cat(cip 余额非负,da_roll 强制校验)

terminal:
  capex_da_ratio: 1.0              # 稳态 capex/D&A(§4.3 第五点)
  perpetual_growth: 0.03

# 三类摊销(无形/使用权/长摊)不在此文件,仍由 yaml1/defaults 管
```

**`base_cip_to_fixed` schema 是 `{year: {cat: amt}}`**(与 `expansion_plan` 同构),不是扁平 list。`da_roll.roll_da_series` 按 cat 提取该类 `{year: amt}`。`base_year` 必须 = `defaults.base_period` 的年份——`load_da_schedule` 校验,不匹配抛 `DaAlignError`,**不在错位数据上滚**(DA 存量快照和 clean_annual base 期必须同一年)。

---

## 第三阶段:落盘与收口

### 产物落盘

`companies\{公司}\Agent\da_schedule.yaml`(`da_schedule_path(company_dir)`)。modify 模式**先归档旧版**到 `Agent\DAhistory\da_schedule_YYYYMMDD.yaml`(加时间戳后缀防覆盖,平移 /ka 的归档纪律),再写新版。init 模式直接写。

`enabled: true` 才被 `forecast.py` 消费;`enabled: false` / 文件缺失 / da_roll 异常 → 自动回退轻资产路径。

### 收口(提示用户重跑)

落盘后提示用户:

```bash
py -m src.forecast --ticker {代码}
```

`forecast.py` 的 `_maybe_roll_da_series` 执行:
1. `load_da_schedule`(base_year 对齐校验,`DaAlignError` 硬抛)。
2. `roll_da_series`(存量稳态折旧 scale 校准 + 扩张 cohort 直线折旧 + cip 转固队列)→ 产 `da_series`(逐年 `ppe_depreciation`/`fix_assets_net`/`cip_balance`/`ppe_capex`/`ppe_capex_split`)。
3. **gpm→ex-dep 覆盖(仅 PP&E 拆分)**:base 年 PP&E 折旧从现金流量表 `depr_fa_coga_dpba` 取(该行 = 固定资产折旧 + 油气资产折耗 + 生产性生物资产折旧,三类同源;da_roll 建模 PP&E + other_depreciating_assets,总量校准到它;三类摊销仍嵌在 gpm 内,与轻资产一致),加回 gpm 得 `gpm_ex_dep = gpm + base_ppe_dep/revenue`。IS 用 `gpm_ex_dep` 算 oper_cost、以 `ppe_depreciation` 作**单一显式 PP&E 折旧行**扣 ebit(三类不显式,仍嵌 oper_cost)。base 年 da_roll 校准使 ppe_dep≈base_ppe_dep,故 EBIT_heavy(base)=EBIT_light(base)(会计中性)。保留 /ka 常规 gpm(loaded)输入语义。
4. 注入 forecast_params → `calc.py` 重资产分支:BS 的 `fix_assets`/`cip` 从 da_series、CF/FCFF 的 capex/da 从 da_series、yaml1 的 `capex_pct` **禁用并告警**。

若 da_roll 异常(非 `DaAlignError`)→ 自动 warning 回退轻资产 + 不阻塞 forecast。

### 终值归一化门提醒(Step 6 实现,现先提)

显式期末须断言"**末年扩张已归一化**",双边量化(spec §9.4):
- `cip_balance / fix_assets_net < ε`(默认 ε=0.05):cip 基本清空(无新 capex 趴着等转固 → 无上行爬坡)。
- `|Δda/da − 预期稳态增速| < δ`(默认 δ=0.05):末年 da 变化率偏离稳态增速小——**同时抓上行**(新 cohort 爬坡)和**下行**(旧 cohort 集中退役)。只测 cip 漏了下行一半。

不满足 → flag 给分析师(不静默放行),标注偏差方向:上行爬坡→da 高→压 nopat→终值低估;下行退役→da 低→抬 nopat→终值高估。残留风险:若显式期怎么都不够长(扩张周期超长,cip 永远转不完)→ 终值 da 是瞬态,flag 给分析师决定拉长显式期或接受瞬态偏差。

---

## 全程纪律(spec §10)

1. **事实↔假设分离**:`da_facts.json`(事实,LLM 扒,只填表不推算,抽不到留 null)vs `da_schedule.yaml`(假设,先押再问拍板才落盘)。
2. **口径对齐**:字段名和 clean_annual 一致(用 TuShare 官方字段名 + da_roll 内部字段)。
3. **capex 不走 `revenue × pct`**(重资产模式 capex 是项目制绝对值排程)。
4. **capex 单一来源**:重资产模式下 BS 与 CF/FCFF 的 capex 同源(da_roll),yaml1 `capex_pct` 禁用并告警。
5. **终值交接平滑**:`capex_da_ratio→1`,末年 da 归一化(双边)。
6. **回退保证**:`enabled: false` / da_schedule 缺失 / da_roll 异常 → 回退轻资产,不阻塞现有公司。
7. **审计**:`da_facts` + 时间戳副本 → `Agent\recon\`;`da_schedule.yaml` → `Agent\`,旧版 → `Agent\DAhistory\`;da_roll 产物 → `Agent\.modelking\`。
8. **诚实于找不到**:exit 3 不改判、找不到证据不凑数、拿不到的值标"待校准/待补旗"。
9. **通用性第一原则**:不写死任何公司特征(行名/业务线数量/年限/单位/拆分层级)。换任何重资产公司只要年报披露了 DA 附注就能跑。见 `CLAUDE.md` 开发总原则。
10. **不读 PDF**:只信任已经翻译进 `.md` 的年报内容。
11. **三类摊销(无形/使用权/长摊)不进 da_schedule**,仍由 yaml1/defaults 管。`da_roll` 只产 `ppe_depreciation`(PP&E 折旧),总 DA 装配在 `calc.py` 一处显式做(不用 `da_total` 这种误导命名)。
12. **不在 2010 前年报上跑**(披露稀疏,对得不偿失——平移 reconciler 2010 闸门)。
