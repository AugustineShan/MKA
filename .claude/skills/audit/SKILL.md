---
name: audit
description: 财务健康度雷达。对 coverage 公司读取 Agent/data.db 的 clean 历史表，生成确定性风险 flags、风险排序和 evidence pack。当用户说 "/audit"、"跑财务健康度检测"、"扫描 coverage 财务造假风险"、"看看谁财务质量最危险" 时使用。
---

# /audit - 财务健康度雷达

`/audit` 只做一件事：用历史 clean 财务数据扫描 coverage 公司，发现财务造假、盈余操纵或财务质量恶化的早期信号。

它不是行情查询，不是交易建议，也不改建模判断。

## 入口命令

```bash
py -m src.audit_engine --coverage all --top 20
py -m src.audit_engine --coverage 002946,002568 --with-evidence
py -m src.audit_engine --coverage D:\path\coverage.txt --with-evidence
```

默认只生成全局雷达。加 `--with-evidence` 后，还会给每家公司写 `Agent/audit/flags_latest.json` 和 `Agent/audit/evidence_pack_latest.json`。

如果只想用本地年报和 recon evidence，不调用 TuShare 辅助接口：

```bash
py -m src.audit_engine --coverage all --with-evidence --no-tushare
```

## 数据源

- 主要数据：`companies/{公司}/Agent/data.db` 的 `clean_annual` / `clean_quarterly`。
- 本地证据：`公告/年报/*.md`、`Agent/recon/*.json`、`financial_expense.yaml`、`da_facts_latest.json`。
- 可选 TuShare 辅助证据：`fina_audit`、`pledge_stat`、`pledge_detail`、`stk_holdertrade`、`block_trade`、`stk_managers`。
- TuShare 字典入口：`D:\MKA\TushareOfficialAPIMD\fulltushare`；接口详档查 `reference\接口文档`，字段速查查 `reference\FIELD_REFERENCE.md`。

## 输出

全局运行目录：

```text
audit_runs/{run_id}/
  flags_matrix.yaml
  risk_ranking.md
  run_manifest.json
```

单公司 evidence：

```text
companies/{公司}/Agent/audit/
  flags_latest.json
  evidence_pack_latest.json
  tushare_aux_cache.json
```

这些都是运行产物。不要手改 `raw_tushare`、`clean_annual`、`clean_quarterly`、核心假设、yaml1 或 forecast 来“修正”审计结果。

## 边界

- 首版只做 Layer 1 确定性 flags + evidence pack，不做 LLM 最终判决。
- 风险排序是财务健康度雷达，不是买卖建议。
- 如果 evidence pack 显示 `verdict.status = not_run`，表示 Layer 2 审计师尚未调查，不要把 flags 当作事实定罪。
