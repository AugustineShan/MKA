# 标准科目词典 field_registry —— 全程序会计科目与排序统一

> 状态:设计稿（待评审）
> 日期:2026-06-22
> 范围决定:B（展示+校验同源）+ B1（元数据同源,check 公式留代码）

## 1. 问题

同一个 TuShare 字段的会计身份（哪张表、哪个 bucket、第几行、叫什么中文名、是不是小计、是不是 resolve 父项、符号怎么定）散落在五个并行声明里,各自维护、已经漂移:

| 来源 | 作用 |
|------|------|
| `clean.py` `IS/BS/CF_FIELD_CATEGORIES` | 驱动硬校验的 bucket 归类 |
| `clean.py` `IS/BS_SUB_RESOLVE`、`SIGN_QUESTIONABLE_IS_FIELDS` | 合并科目拆分、符号语义 |
| `workbench.py` `STATEMENT_META.field_order/category_order/subtotal_after` | 展示用会计序 + 小计挂载 |
| `workbench.py` `LABEL_OVERRIDE` + `FIELD_REFERENCE`(解析 `数据格式参考.md`) | 标签 + 标签补丁 |
| `generate_field_reference.py` | 号称从 clean.py 生成文档,实际已 stale |

**已观测到的漂移**:`credit_impa_loss` 在 `clean.py:166` 是 `operating_adjustment`,在 `数据格式参考.md:44` 是 `cost_item`——文档未随 clean.py 重生。`assets_impair_loss` 同样漂移。`LABEL_OVERRIDE` 的存在本身说明代码在迁就一个 stale 文档。

前端 `_statement_rows`(workbench.py:421-486)为了排一次会计序,要协调 `FIELD_REFERENCE` + `field_order` + `category_order` + `subtotal_after` + `LABEL_OVERRIDE` 五源,改一漏四。

## 2. 目标

**一份 YAML,是全部 325 个 TuShare 官方字段 + 6 个 QA plug 字段的元数据唯一真源。** `clean.py` 的分类/resolve/sign 与 `workbench.py` 的排序/标签都从它读;`数据格式参考.md` 由它重新生成。`check_is/bs/cf` 的 subtotal 公式不动（B1）。

## 3. 决定

- **B**:展示层与校验层同源。
- **B1**:元数据同源,check 公式留代码。
- **结构**:flat 有序列表。列表顺序 = 会计序 = 前端展示序。`category_order` 由 `categories:` 有序 map 显式声明;`subtotal_after` 由小计字段在列表中的位置隐式表达;`LABEL_OVERRIDE` 溶解进 `label`(直接带"减:/其中:"前缀)。
- **`role: total`**:BS 的 `total_assets`/`total_liab`/`total_liab_hldr_eqy` 三个总计在词典标 `role: total`,前端不再特判。
- **格式**:YAML 声明文件(贴项目"驱动来自声明"第一原则)。
- **落位**:`src/field_registry.yaml`(真源) + `src/field_registry.py`(loader)。放 `src/` 因其是 clean.py/workbench.py 的 import 期依赖,与消费方同目录。

## 4. 词典 schema

```yaml
version: 1
statements:
  income:
    name: 利润表
    unit: 百万元
    categories:               # 有序 map:顺序 = bucket 展示序;值 = 中文 bucket 标签
      revenue_item: 收入项
      cost_item: 成本项
      operating_adjustment: 营业利润调节项
      below_line: 营业外收支
      tax: 所得税
      attribution: 净利润归属
      comprehensive: 综合收益
      subtotal: 小计/合计
      sub_item: 子明细
      derived: 衍生/不参与加总
    fields:                   # 有序列表:顺序 = 会计准则序 = 前端展示序
      - {field: revenue, label: 营业收入, category: revenue_item}
      - {field: oper_cost, label: 减:营业成本, category: cost_item}
      - {field: total_cogs, label: 营业总成本, category: subtotal}
      - {field: invest_income, label: 投资收益, category: operating_adjustment,
         resolve_children: [ass_invest_income, amodcost_fin_assets]}
      - {field: ass_invest_income, label: 其中:对联营和合营企业的投资收益,
         category: sub_item, resolve_parent: invest_income}
      - {field: assets_impair_loss, label: 减:资产减值损失,
         category: operating_adjustment, sign: questionable}
  balancesheet:
    name: 资产负债表
    unit: 百万元
    categories: {current_asset: 流动资产, noncurrent_asset: 非流动资产,
                 current_liab: 流动负债, noncurrent_liab: 非流动负债,
                 equity: 所有者权益, subtotal: 小计/合计, ...}
    fields:
      - {field: money_cap, label: 货币资金, category: current_asset}
      ...
      - {field: total_assets, label: 资产总计, category: subtotal, role: total}
      - {field: total_liab, label: 负债合计, category: subtotal, role: total}
      - {field: total_liab_hldr_eqy, label: 负债和所有者权益总计, category: subtotal, role: total}
  cashflow:
    name: 现金流量表
    unit: 百万元
    categories: {cfo_inflow: 经营活动流入, cfo_outflow: 经营活动流出, ...}
    fields:
      - {field: c_fr_sale_sg, label: 销售商品提供劳务收到的现金, category: cfo_inflow}
      ...
```

### 字段维度（每条 field 最多七维）
| 维度 | 必填 | 取代现在的 | 说明 |
|------|------|-----------|------|
| `field` | 是 | — | TuShare 官方字段名 |
| `label` | 是 | `数据格式参考.md` label + `LABEL_OVERRIDE` | 含"减:/其中:"前缀的展示标签 |
| `category` | 是 | `FIELD_CATEGORIES` | bucket 归类 |
| `resolve_children` | 否 | `IS/BS_SUB_RESOLVE` | 父项→子明细列表 |
| `resolve_parent` | 否 | （新增,反向索引） | 子项→父项,校验用 |
| `sign` | 否 | `SIGN_QUESTIONABLE_IS_FIELDS` | `questionable` 表示符号已带会计含义 |
| `role` | 否 | 前端 `subtotal_after` 特判 | `total`=总计粗体;缺省按 `category==subtotal` 判小计 |

### loader 暴露(`src/field_registry.py`)
`FIELD_CATEGORIES_IS/BS/CF`、`FIELD_ORDER_IS/BS/CF`、`CATEGORY_ORDER_*`、`CATEGORY_LABELS_*`、`LABELS`、`RESOLVE_*`、`SIGN_QUESTIONABLE`、`TOTAL_FIELDS`。启动时解析一次缓存。

## 5. 消费方改造（机械替换,零逻辑变更）

| 现在 | 改成 |
|------|------|
| `clean.py` `IS/BS/CF_FIELD_CATEGORIES` | `from .field_registry import FIELD_CATEGORIES_*` |
| `clean.py` `IS/BS_SUB_RESOLVE` | `RESOLVE_*` |
| `clean.py` `SIGN_QUESTIONABLE_IS_FIELDS` | `SIGN_QUESTIONABLE` |
| `workbench.STATEMENT_META.field_order/category_order/subtotal_after` | registry `FIELD_ORDER_*`/`CATEGORY_ORDER_*` + 列表位置 |
| `workbench.FIELD_REFERENCE` 解析 + `LABEL_OVERRIDE` | registry `LABELS`(整段删除) |
| `workbench._statement_rows` 五源合流 | 直接迭代 `registry.fields`,`role` 看 `category==subtotal` 或 `role==total` |
| `generate_field_reference.py` 从 clean.py 抓 | 改为从 registry 生成 `数据格式参考.md` |

`_statement_rows` 改造后:删 `FIELD_REFERENCE` 解析、删 `by_category` 排序、删 `subtotal_after` 追加、删 `LABEL_OVERRIDE`。直接按 `registry.fields` 顺序产 row,前端代码显著变短。

## 6. 🔴 Day-1 零行为变更契约（最关键）

1. **逐字段复刻现状**。registry 的 category/resolve/sign 照搬 `clean.py` 现值,包括看起来不一致的(`credit_impa_loss=operating_adjustment` 照搬,不"修"成 `cost_item`)。`数据格式参考.md` 由 registry 重生,漂移自动收敛到 clean.py 的真。
2. **"这字段分类对不对"是后续独立决策**,每条单独验证 + 重跑 clean,不绑进本次迁移。
3. **switch-over 前等价性测试**:
   - `registry.FIELD_CATEGORIES_IS == clean.py.IS_FIELD_CATEGORIES`(BS/CF 同理),逐字段。
   - `registry.FIELD_ORDER_IS == workbench.STATEMENT_META['forecast_is.csv'].field_order`(BS/CF 同理)。
   - `registry.LABELS[field] == LABEL_OVERRIDE.get(field, FIELD_REFERENCE_label[field])` 全等。
4. **四家回归**:美的(000333)/紫金(601899)/茅台(600519)/比亚迪(002594)。切换前后:
   - `clean --mode annual` 与 `--mode quarterly` 的 `clean_annual`/`clean_quarterly` 输出 byte-identical。
   - `_statement_rows` 渲染的三表 rows 逐行 `field/label/category/role/level` 全等。
   - 任何不一致不切换。

## 7. 迁移步骤（seed for implementation plan）

1. 建 `src/field_registry.yaml`——转录 clean.py 三表 `FIELD_CATEGORIES`(category)+ workbench `field_order`(order)+ `subtotal_after`(小计位置)+ `category_order`+ `LABEL_OVERRIDE`(label 带前缀)+ `数据格式参考.md` 中文 label + `SUB_RESOLVE`/`SIGN_QUESTIONABLE`。覆盖 325 官方字段 + 6 QA plug。
2. 建 `src/field_registry.py` loader + 上述暴露接口。
3. 写等价性测试(第 6 条三组断言)。
4. 切 `clean.py` import registry,删本地字典。
5. 切 `workbench._statement_rows` 消费 registry,删 `FIELD_REFERENCE`/`LABEL_OVERRIDE`/`STATEMENT_META` 冗余字段。
6. 重写 `generate_field_reference.py` 从 registry 生成文档。
7. 跑四家回归(第 6 条第 4 点)。
8. 更新 `docs/ARCHITECTURE.md` + `docs/数据流水线.md` + `CLAUDE.md` 字段命名/分类章节。

## 8. 明确不做（YAGNI）

- `check_*` 公式数据驱动(B2)——不碰稳定校验。
- `known_tushare_defects.json` 并入——独立关注点,JSON 现状够用。
- 公司级 override——违反第一原则,词典字段级、公司无关。
- 金融企业字段显式行序——comp_type≠1 已过滤;给 category、不排显式序,回退类内字母序(与现状一致)。
- `field_terms.csv` / `statement_field_coverage.csv`——CLAUDE.md 提及但不存在,不新建。

## 9. 风险

- **clean.py import 期文件 IO**:loader 缺文件 fail-loud,文件入 repo,解析缓存一次。
- **迁移打破已过公司**:第 6 条等价性测试 + 四家回归兜底。
- **label 带前缀 vs TuShare 原标签**:`数据格式参考.md` 重生后 label 是会计惯例版(带"减:"),若需保留 TuShare 原标签作单独列,在生成脚本里加 `tushare_label` 列。
