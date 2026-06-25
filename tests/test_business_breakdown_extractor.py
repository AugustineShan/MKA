from pathlib import Path

import src.business_breakdown_extractor as bbe
from src.business_breakdown_extractor import extract_report, write_company_outputs
from src.company_paths import annual_reports_dir, official_breakdowns_dir, quarterly_reports_dir


def write_report(tmp_path: Path, body: str) -> Path:
    company_dir = tmp_path / "companies" / "样本公司_600000"
    annuals = annual_reports_dir(company_dir)
    annuals.mkdir(parents=True)
    report = annuals / "2024_年度报告.md"
    report.write_text(body, encoding="utf-8")
    return report


def write_h1_report(tmp_path: Path, year: int, body: str) -> Path:
    company_dir = tmp_path / "companies" / "样本公司_600000"
    h1_dir = quarterly_reports_dir(company_dir) / str(year)
    h1_dir.mkdir(parents=True)
    report = h1_dir / f"{year}_半年度报告.md"
    report.write_text(f'---\nyear: {year}\nkind: "h1"\n---\n\n{body}', encoding="utf-8")
    return report


def test_extracts_sse_style_product_rows_with_wrapped_names(tmp_path: Path):
    report = write_report(
        tmp_path,
        """
2、 收入和成本分析
(1). 主营业务分行业、分产品、分地区、分销售模式情况
单位：元 币种：人民币
主营业务分产品情况
分产品
营业收入
营业成本
毛利率
（%）
营业收入比上年增减（%）
营业成本比上年增减（%）
毛利率比上年增减
茅台酒
145,928,075,955.31
8,662,079,388.78
94.06
15.28
16.34
减少0.06
个百分点
其他系列
酒
24,683,762,096.71
4,967,916,424.11
79.87
19.65
19.00
增加0.11
个百分点
主营业务分地区情况
分地区
营业收入
营业成本
毛利率
国内
165,423,308,808.24
13,226,875,459.60
92.00
15.79
17.26
减少0.1
个百分点
主营业务分行业、分产品、分地区、分销售模式情况的说明
无
""",
    )

    rows = extract_report(report)
    products = [row for row in rows if row.dimension == "product"]

    assert [row.item_name for row in products] == ["茅台酒", "其他系列酒"]
    assert products[0].source_table == "major_business_profitability"
    assert products[0].revenue_yuan == 145_928_075_955.31
    assert products[0].cost_yuan == 8_662_079_388.78
    assert products[0].gross_margin_pct == 94.06
    assert products[0].gross_margin_change == "减少0.06个百分点"
    assert products[1].item_name == "其他系列酒"


def test_extracts_szse_revenue_composition_and_profitability_tables(tmp_path: Path):
    report = write_report(
        tmp_path,
        """
2、收入与成本
（1） 营业收入构成
单位：元
2024 年
2023 年
同比增减
金额
占营业收入比重
金额
占营业收入比重
分产品
充电储能类
12,667,006,821.10
51.26%
8,603,582,343.89
49.14%
47.23%
智能创新类
6,336,476,919.10
25.64%
4,541,290,907.94
25.94%
39.53%
（2） 占公司营业收入或营业利润10%以上的行业、产品、地区、销售模式的情况
单位：元
营业收入
营业成本
毛利率
营业收入比上年同期增减
营业成本比上年同期增减
毛利率比上年同期增减
分产品
充电储能类
12,667,006,821.10
7,415,203,131.88
41.46%
47.23%
49.26%
-0.80%
分地区
境外
23,825,145,042.27
96.42%
16,869,249,360.70
96.36%
41.23%
公司实物销售收入是否大于劳务收入
""",
    )

    rows = extract_report(report)
    composition = [
        row
        for row in rows
        if row.dimension == "product" and row.source_table == "revenue_composition"
    ]
    profitability = [
        row
        for row in rows
        if row.dimension == "product" and row.source_table == "major_business_profitability"
    ]
    regions = [row for row in rows if row.dimension == "region"]

    assert [row.item_name for row in composition] == ["充电储能类", "智能创新类"]
    assert composition[0].revenue_pct == 51.26
    assert composition[0].revenue_previous_yuan == 8_603_582_343.89
    assert composition[0].revenue_yoy_pct == 47.23
    assert profitability[0].cost_yuan == 7_415_203_131.88
    assert profitability[0].gross_margin_change == "-0.80%"
    assert regions[0].item_name == "境外"
    assert regions[0].source_table == "business_profitability_yoy_split"


def test_applies_unit_multiplier_for_thousand_yuan(tmp_path: Path):
    report = write_report(
        tmp_path,
        """
主营业务分产品情况
单位：千元 币种：人民币
分产品
营业收入
营业成本
毛利率
工程机械
75,831,195
55,640,721
26.63
6.03
5.36
增加0.47 个百分点
主营业务分行业、分产品、分地区、分销售模式情况的说明
""",
    )

    rows = extract_report(report)

    assert len(rows) == 1
    assert rows[0].revenue_unit == "千元"
    assert rows[0].revenue_yuan == 75_831_195_000.0


def test_writes_outputs_under_company_agent_official_breakdowns(tmp_path: Path):
    report = write_report(
        tmp_path,
        """
主营业务分产品情况
单位：千元 币种：人民币
分产品
营业收入
营业成本
毛利率
工程机械
75,831,195
55,640,721
26.63
6.03
5.36
增加0.47 个百分点
主营业务分行业、分产品、分地区、分销售模式情况的说明
""",
    )
    company_dir = report.parents[2]
    rows = extract_report(report)

    outputs = write_company_outputs(rows, tmp_path / "companies")

    assert len(outputs) == 1
    out_dir = official_breakdowns_dir(company_dir)
    assert outputs[0][1] == out_dir / "business_revenue_breakdown.csv"
    assert outputs[0][2] == out_dir / "business_revenue_breakdown.jsonl"
    assert (out_dir / "business_revenue_breakdown.csv").exists()
    assert (out_dir / "business_revenue_breakdown.jsonl").exists()


def test_extract_reports_uses_configured_parallel_workers(tmp_path: Path, monkeypatch):
    report = write_report(
        tmp_path,
        """
主营业务分产品情况
单位：千元 币种：人民币
分产品
营业收入
营业成本
毛利率
工程机械
75,831,195
55,640,721
26.63
6.03
5.36
增加0.47 个百分点
主营业务分行业、分产品、分地区、分销售模式情况的说明
""",
    )
    calls: dict[str, int | None] = {}

    def fake_parallel_map(func, items, *, max_workers=None):
        calls["max_workers"] = max_workers
        return [func(item) for item in items]

    monkeypatch.setattr(bbe, "parallel_map", fake_parallel_map)

    rows = bbe.extract_reports([report], max_workers=3)

    assert calls["max_workers"] == 3
    assert len(rows) == 1


def test_extracts_h1_report_with_period_identity(tmp_path: Path):
    report = write_h1_report(
        tmp_path,
        2025,
        """
主营业务分产品情况
单位：千元 币种：人民币
分产品
营业收入
营业成本
毛利率
工程机械
75,831,195
55,640,721
26.63
6.03
5.36
增加0.47 个百分点
主营业务分行业、分产品、分地区、分销售模式情况的说明
""",
    )

    rows = extract_report(report)

    assert len(rows) == 1
    assert rows[0].year == 2025
    assert rows[0].period == "2025H1"
    assert rows[0].period_type == "h1"
    assert rows[0].period_label == "半年度"


def test_discovers_recent_three_h1_reports(tmp_path: Path):
    write_report(tmp_path, "无")
    for year in (2021, 2022, 2023, 2024, 2025):
        write_h1_report(tmp_path, year, "无")

    reports = bbe.discover_reports(tmp_path / "companies", tickers={"600000"}, include_h1=True, h1_recent_years=3)

    assert [report.name for report in reports if "半年度" in report.name] == [
        "2023_半年度报告.md",
        "2024_半年度报告.md",
        "2025_半年度报告.md",
    ]


def test_writes_h1_and_all_outputs(tmp_path: Path):
    report = write_h1_report(
        tmp_path,
        2025,
        """
主营业务分产品情况
单位：千元 币种：人民币
分产品
营业收入
营业成本
毛利率
工程机械
75,831,195
55,640,721
26.63
6.03
5.36
增加0.47 个百分点
主营业务分行业、分产品、分地区、分销售模式情况的说明
""",
    )
    company_dir = report.parents[3]
    rows = extract_report(report)

    outputs = write_company_outputs(rows, tmp_path / "companies")

    out_dir = official_breakdowns_dir(company_dir)
    assert len(outputs) == 1
    assert (out_dir / "business_revenue_breakdown_h1.csv").exists()
    assert (out_dir / "business_revenue_breakdown_h1.jsonl").exists()
    assert (out_dir / "business_revenue_breakdown_all.csv").exists()
    assert (out_dir / "business_revenue_breakdown_all.jsonl").exists()

