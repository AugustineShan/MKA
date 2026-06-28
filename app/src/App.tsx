import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import type {
  AnnualRevenueBreakdownRow,
  AppSettings,
  ArchiveModelsResult,
  AssumptionPatch,
  AssumptionPreview,
  AssumptionsKnob,
  CompanyDetail,
  CompanySummary,
  DcfDetailRow,
  DerivedMetrics,
  DisplayBlock,
  DisplayWarning,
  EditableAssumption,
  EditableAssumptionCell,
  HomeFolderOverview,
  IndustryData,
  PipelineStage,
  QuarterlyRow,
  QuarterlyView,
  RatingReportSettings,
  ReverseDcfBase,
  StashBlock,
  StatementRow,
  StatementSheet,
  TabKey,
  TerminalView,
  Yaml1AssumptionsView,
  Yaml1DisplayContract,
  Yaml1Presentation,
  Yaml1RevenueSegment,
  Yaml1RevenueView,
} from "./types";
import { Tutorial } from "./Tutorial";
import DaSchedule from "./DaSchedule";
import {
  clampValue,
  defaultReverseDcfInputs,
  evaluateReverseDcf,
  generateIsoCurve,
  nearestCurvePoint,
  pointInDomain,
  referenceIntersection,
  referencePointForTargetG2,
  modelSegmentCagr,
  solveWaccForModelG1Parity,
} from "./reverseDcf";
import type { ModelSegmentCagr, ReverseDcfInputs, ReverseDcfPoint } from "./reverseDcf";

const tabs: Array<{ key: TabKey; label: string }> = [
  { key: "overview", label: "Overview" },
  { key: "yaml1", label: "核心假设展示" },
  { key: "statements", label: "完整三表" },
  { key: "dcf", label: "DCF" },
  { key: "reverse", label: "逆向 DCF" },
  { key: "quarterly", label: "季度展示" },
  { key: "da", label: "D&A" },
];

async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) throw new Error(await response.text());
  return response.json() as Promise<T>;
}

async function apiPost<T>(path: string): Promise<T> {
  const response = await fetch(path, { method: "POST" });
  if (!response.ok) throw new Error(await response.text());
  return response.json() as Promise<T>;
}

async function apiPostJson<T>(path: string, body: Record<string, unknown>): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json() as Promise<T>;
}

async function previewAssumptions(companyId: string, patches: AssumptionPatch[]): Promise<AssumptionPreview> {
  return apiPostJson<AssumptionPreview>(
    `/api/companies/${encodeURIComponent(companyId)}/assumption-preview`,
    { patches },
  );
}

async function generateAssumptionBrief(
  companyId: string,
  patches: AssumptionPatch[],
): Promise<{ prompt: string }> {
  return apiPostJson<{ prompt: string }>(
    `/api/companies/${encodeURIComponent(companyId)}/assumption-brief`,
    { patches },
  );
}

async function apiPutJson<T>(path: string, body: Record<string, unknown>): Promise<T> {
  const response = await fetch(path, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json() as Promise<T>;
}

async function apiDelete<T>(path: string): Promise<T> {
  const response = await fetch(path, { method: "DELETE" });
  if (!response.ok) throw new Error(await response.text());
  return response.json() as Promise<T>;
}

function formatNumber(value: unknown, digits = 0): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "-";
  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);
}

function formatPercent(value: unknown, digits = 1): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "-";
  return `${new Intl.NumberFormat("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value * 100)}%`;
}

function formatSignedPercent(value: unknown, digits = 1): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "-";
  const formatted = formatPercent(value, digits);
  return value > 0 ? `+${formatted}` : formatted;
}

function formatPctPoint(value: unknown, digits = 1): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "-";
  return `${new Intl.NumberFormat("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value)}%`;
}

function formatSignedPctPoint(value: unknown, digits = 1): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "-";
  const formatted = formatPctPoint(value, digits);
  return value > 0 ? `+${formatted}` : formatted;
}

function formatYuan(value: unknown): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "-";
  const abs = Math.abs(value);
  if (abs >= 100_000_000) return `${formatNumber(value / 100_000_000, 1)} 亿`;
  if (abs >= 10_000) return `${formatNumber(value / 10_000, 1)} 万`;
  return formatNumber(value, 0);
}

function formatYiFromMillion(value: unknown, digits = 1): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "-";
  return formatNumber(value / 100, digits);
}

function formatMultiple(value: unknown, digits = 1): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "-";
  return `${formatNumber(value, digits)}x`;
}

function asNumber(value: unknown): number | null {
  return typeof value === "number" && !Number.isNaN(value) ? value : null;
}

function calcCagr(start: number, end: number | undefined, periods: number): number | null {
  if (!end || start <= 0 || periods <= 0) return null;
  return (end / start) ** (1 / periods) - 1;
}

function average(values: Array<number | null>): number | null {
  const finite = values.filter((value): value is number => typeof value === "number" && !Number.isNaN(value));
  if (!finite.length) return null;
  return finite.reduce((sum, value) => sum + value, 0) / finite.length;
}

function yearOverYear(series: Record<string, number> | undefined, year: string): number | null {
  if (!series) return null;
  const current = series[year];
  const previous = series[String(Number(year) - 1)];
  if (typeof current !== "number" || typeof previous !== "number" || previous === 0) return null;
  return current / previous - 1;
}

function statementValue(sheet: StatementSheet | undefined, fields: string[], year: string): number | null {
  if (!sheet) return null;
  for (const field of fields) {
    const row = sheet.rows.find((item) => item.field === field);
    const value = row?.values?.[year];
    if (typeof value === "number" && !Number.isNaN(value)) return value;
  }
  return null;
}

function formatDate(seconds?: number | null): string {
  if (!seconds) return "Not generated";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(seconds * 1000));
}

function statValue(summary: CompanySummary, key: string): unknown {
  const raw = summary as unknown as Record<string, unknown>;
  return raw[key];
}

function Sidebar({
  companies,
  selectedId,
  onSelect,
  loading,
  homeActive,
  onSelectHome,
}: {
  companies: CompanySummary[];
  selectedId?: string;
  onSelect: (id: string) => void;
  loading: boolean;
  homeActive: boolean;
  onSelectHome: () => void;
}) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-title">ModelKing</div>
        <div className="brand-subtitle">Buy-side workbench</div>
      </div>
      <button
        className={`company-item home-item ${homeActive ? "selected" : ""}`}
        onClick={onSelectHome}
        type="button"
      >
        <span className="company-name">首页</span>
        <span className="company-code">Home</span>
      </button>
      <div className="sidebar-section-label">Companies</div>
      <div className="company-list">
        {loading ? <div className="activity">Loading companies</div> : null}
        {companies.map((company) => (
          <button
            className={`company-item ${!homeActive && selectedId === company.id ? "selected" : ""}`}
            key={company.id}
            onClick={() => onSelect(company.id)}
            type="button"
          >
            <span className="company-name">{company.name}</span>
            <span className="company-code">{company.industry ?? company.code}</span>
          </button>
        ))}
      </div>
    </aside>
  );
}

function StatusPill({ label, tone = "neutral" }: { label: string; tone?: "neutral" | "blue" | "red" }) {
  return <span className={`status-pill ${tone}`}>{label}</span>;
}

function MetricCard({ label, value, caption, tone = "default" }: { label: string; value: string; caption?: string; tone?: "default" | "highlight" }) {
  return (
    <div className={`metric-card ${tone === "highlight" ? "metric-card-highlight" : ""}`}>
      <div className="eyebrow">{label}</div>
      <div className="metric-value">{value}</div>
      {caption ? <div className="metric-caption">{caption}</div> : null}
    </div>
  );
}

const DEFAULT_RATING_REPORT_CONFIG: RatingReportSettings = {
  data_start_year: 2023,
  data_end_year: 2025,
  forecast_start_year: 2026,
  forecast_end_year: 2028,
};

const overviewRows: Array<{
  metric: string;
  label: string;
  format: "number" | "percent" | "signedPercent" | "multiple" | "decimal";
  major?: boolean;
}> = [
  { metric: "revenue", label: "营业收入", format: "number", major: true },
  { metric: "revenue_yoy", label: "同比", format: "signedPercent" },
  { metric: "gross_margin", label: "毛利率", format: "percent" },
  { metric: "n_income_attr_p", label: "归母净利润", format: "number", major: true },
  { metric: "n_income_attr_p_yoy", label: "同比", format: "signedPercent" },
  { metric: "eps", label: "EPS", format: "decimal" },
  { metric: "roe", label: "ROE", format: "percent" },
  { metric: "pe", label: "PE", format: "multiple" },
  { metric: "pb", label: "PB", format: "multiple" },
  { metric: "ev_ebitda", label: "EV/EBITDA", format: "multiple" },
];

function overviewRange(config?: RatingReportSettings) {
  const active = config ?? DEFAULT_RATING_REPORT_CONFIG;
  const years: Array<{ year: number; label: string; forecast: boolean }> = [];
  for (let year = active.data_start_year; year <= active.data_end_year; year += 1) {
    years.push({ year, label: String(year), forecast: false });
  }
  for (let year = active.forecast_start_year; year <= active.forecast_end_year; year += 1) {
    if (!years.some((item) => item.year === year)) {
      years.push({ year, label: `${year}E`, forecast: true });
    }
  }
  return years;
}

function forecastYearLabel(year: number | undefined): string {
  return typeof year === "number" ? `${year}E` : "-";
}

function overviewMetric(detail: CompanyDetail, metric: string, year: number): number | null {
  const yearKey = String(year);
  const ratingRow = detail.derived_metrics?.rating_report_rows?.find((row) => row.metric === metric);
  const ratingValue = ratingRow?.values?.[yearKey];
  if (typeof ratingValue === "number" && !Number.isNaN(ratingValue)) return ratingValue;
  const annualValue = detail.derived_metrics?.annual?.[yearKey]?.[metric];
  return typeof annualValue === "number" && !Number.isNaN(annualValue) ? annualValue : null;
}

function formatOverviewMetric(value: number | null, format: (typeof overviewRows)[number]["format"]): string {
  if (format === "percent") return formatPercent(value, 1);
  if (format === "signedPercent") return formatSignedPercent(value, 1);
  if (format === "multiple") return formatMultiple(value, 1);
  if (format === "decimal") return formatNumber(value, 2);
  return formatNumber(value);
}

function formatMarketDate(value: unknown): string {
  const text = String(value ?? "");
  if (/^\d{8}$/.test(text)) return `${text.slice(0, 4)}/${text.slice(4, 6)}/${text.slice(6, 8)}`;
  return text || "-";
}

function Overview({ detail }: { detail: CompanyDetail }) {
  const { summary, dcf_summary: dcf } = detail;
  const market = detail.derived_metrics?.market_snapshot ?? {};
  const valuation = detail.derived_metrics?.valuation ?? {};
  const ratingConfig = detail.rating_report ?? DEFAULT_RATING_REPORT_CONFIG;
  const years = overviewRange(detail.rating_report);
  const forecastYears = years.filter((year) => year.forecast);
  const forecastFirstYear = forecastYears[0]?.year ?? ratingConfig.forecast_start_year;
  const forecastSecondYear = forecastYears[1]?.year ?? forecastFirstYear + 1;
  const forecastLastYear = forecastYears[forecastYears.length - 1]?.year ?? ratingConfig.forecast_end_year;
  const forecastPeriodLabel = `${forecastYearLabel(forecastFirstYear)}-${forecastYearLabel(forecastLastYear)}`;
  const currentPrice = asNumber(market.close);
  const perShareValue = asNumber(valuation.per_share_value ?? dcf?.per_share_value ?? summary.per_share_value);
  const impliedUpside = currentPrice && perShareValue ? perShareValue / currentPrice - 1 : null;
  const marketCap = asNumber(market.total_mv ?? overviewMetric(detail, "market_cap", forecastFirstYear));
  const firstForecastPe = overviewMetric(detail, "pe", forecastFirstYear) ?? asNumber(valuation.forward_pe);
  const secondForecastPe = overviewMetric(detail, "pe", forecastSecondYear);
  const revenueCagr = forecastFirstYear && forecastLastYear
    ? calcCagr(
      overviewMetric(detail, "revenue", forecastFirstYear) ?? 0,
      overviewMetric(detail, "revenue", forecastLastYear) ?? undefined,
      forecastLastYear - forecastFirstYear,
    )
    : null;
  const profitCagr = forecastFirstYear && forecastLastYear
    ? calcCagr(
      overviewMetric(detail, "n_income_attr_p", forecastFirstYear) ?? 0,
      overviewMetric(detail, "n_income_attr_p", forecastLastYear) ?? undefined,
      forecastLastYear - forecastFirstYear,
    )
    : null;
  const grossMarginChange = forecastFirstYear && forecastLastYear
    ? ((overviewMetric(detail, "gross_margin", forecastLastYear) ?? NaN) - (overviewMetric(detail, "gross_margin", forecastFirstYear) ?? NaN)) * 100
    : null;
  const roeMidpoint = average(forecastYears.map((year) => overviewMetric(detail, "roe", year.year)));

  return (
    <div className="view-stack overview-page">
      <section className="overview-hero">
        <div className="overview-hero-copy">
          <div className="eyebrow">Investment snapshot</div>
          <h1>{summary.name}</h1>
          <p>
            {summary.ticker ?? summary.code} · 行情日 {formatMarketDate(market.trade_date)}
          </p>
        </div>
        <div className="overview-price-panel">
          <div>
            <span>现价</span>
            <strong>{formatNumber(currentPrice, 2)}</strong>
          </div>
          <div>
            <span>DCF 价值</span>
            <strong>{formatNumber(perShareValue, 2)}</strong>
          </div>
          <div className={impliedUpside != null && impliedUpside >= 0 ? "positive" : "negative"}>
            <span>隐含空间</span>
            <strong>{formatSignedPercent(impliedUpside, 1)}</strong>
          </div>
        </div>
      </section>

      <section className="overview-kpi-grid">
        <div className="overview-kpi">
          <span>市值</span>
          <strong>{formatYiFromMillion(marketCap)}</strong>
          <small>亿元</small>
        </div>
        <div className="overview-kpi">
          <span>{forecastYearLabel(forecastFirstYear)} PE</span>
          <strong>{formatMultiple(firstForecastPe, 1)}</strong>
          <small>未来估值</small>
        </div>
        <div className="overview-kpi">
          <span>{forecastYearLabel(forecastSecondYear)} PE</span>
          <strong>{formatMultiple(secondForecastPe, 1)}</strong>
          <small>未来估值</small>
        </div>
      </section>

      <section className="overview-grid">
        <aside className="overview-driver-card">
          <div className="overview-card-head compact">
            <div>
              <div className="eyebrow">Profit drivers</div>
              <h2>增长与盈利</h2>
            </div>
          </div>
          <div className="overview-driver-list">
            <div>
              <span>{forecastPeriodLabel} 收入 CAGR</span>
              <strong>{formatPercent(revenueCagr, 1)}</strong>
            </div>
            <div>
              <span>{forecastPeriodLabel} 归母净利 CAGR</span>
              <strong>{formatPercent(profitCagr, 1)}</strong>
            </div>
            <div>
              <span>{forecastPeriodLabel} 毛利率变化</span>
              <strong>{formatSignedPctPoint(Number.isNaN(grossMarginChange) ? null : grossMarginChange, 1)}</strong>
            </div>
            <div>
              <span>{forecastPeriodLabel} ROE 中枢</span>
              <strong>{formatPercent(roeMidpoint, 1)}</strong>
            </div>
          </div>
        </aside>

        <div className="overview-financial-card">
          <div className="overview-card-head">
            <div>
              <div className="eyebrow">Financial snapshot</div>
              <h2>财务总结</h2>
            </div>
            <span>单位：百万元；倍数除外</span>
          </div>
          <div className="table-scroll overview-table-wrap">
            <table className="overview-financial-table">
              <thead>
                <tr>
                  <th>指标</th>
                  {years.map((year) => (
                    <th className={year.forecast ? "forecast-year" : ""} key={year.label}>{year.label}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {overviewRows.map((row) => (
                  <tr className={row.major ? "major" : ""} key={row.metric}>
                    <td>{row.label}</td>
                    {years.map((year) => {
                      const value = overviewMetric(detail, row.metric, year.year);
                      return (
                        <td className={`${value != null && value < 0 ? "negative" : ""} ${year.forecast ? "forecast-year" : ""}`} key={year.label}>
                          {formatOverviewMetric(value, row.format)}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>
    </div>
  );
}

function SheetTabs({
  items,
  active,
  onSelect,
}: {
  items: Array<{ key: string; label: string; count?: number }>;
  active: string;
  onSelect: (key: string) => void;
}) {
  return (
    <div className="sheet-tabs" role="tablist">
      {items.map((item) => (
        <button className={active === item.key ? "active" : ""} key={item.key} onClick={() => onSelect(item.key)} type="button">
          <span>{item.label}</span>
          {typeof item.count === "number" ? <small>{item.count}</small> : null}
        </button>
      ))}
    </div>
  );
}

function RevenueAssumptions({
  page,
  presentation,
  statementSheets,
  view,
}: {
  page: "summary" | "detail";
  presentation?: Yaml1Presentation | null;
  statementSheets?: StatementSheet[];
  view: Yaml1RevenueView;
}) {
  const columns = [String(view.base_year), ...view.years];
  const lastYear = view.years[view.years.length - 1];
  const lastRevenue = lastYear ? view.revenues[lastYear] : undefined;
  const incomeSheet = statementSheets?.find((sheet) => sheet.key === "is");
  const focusYears = view.years.slice(0, 3);
  const historyYears = useMemo(() => {
    const years = new Set<string>();
    view.segments.forEach((segment) => {
      Object.keys(segment.history_revenues ?? {}).forEach((year) => years.add(year));
    });
    return [...years].sort();
  }, [view.segments]);
  const forecastRows = [
    {
      label: "营业收入",
      values: Object.fromEntries(focusYears.map((year) => [year, statementValue(incomeSheet, ["revenue"], year) ?? view.revenues[year] ?? null])),
    },
    {
      label: "营业利润",
      values: Object.fromEntries(focusYears.map((year) => [year, statementValue(incomeSheet, ["operate_profit"], year)])),
    },
    {
      label: "归母净利",
      values: Object.fromEntries(focusYears.map((year) => [year, statementValue(incomeSheet, ["n_income_attr_p", "n_income"], year)])),
    },
  ];
  const orderedSegments = useMemo(() => {
    const wanted = presentation?.segment_order ?? [];
    if (!wanted.length) return view.segments;
    const rank = new Map(wanted.map((name, index) => [name, index]));
    return [...view.segments].sort((left, right) => {
      const leftRank = rank.get(left.name) ?? Number.MAX_SAFE_INTEGER;
      const rightRank = rank.get(right.name) ?? Number.MAX_SAFE_INTEGER;
      return leftRank - rightRank;
    });
  }, [presentation?.segment_order, view.segments]);
  const insightItems = presentation?.insights?.filter(Boolean) ?? [];
  const riskItems = presentation?.risks?.filter(Boolean) ?? [];

  return (
    <div className="revenue-assumptions">
      {page === "summary" ? (
        <>
          <section className="business-hero">
            <div>
              <div className="eyebrow">Business view</div>
              <h2>{presentation?.title || "收入模型"}</h2>
              <p>{presentation?.subtitle || "按业务线拆分收入，再把每条线的销量、价格或收入增速展开到预测期。金额单位：百万元。"}</p>
              {presentation ? (
                <details className="presentation-meta">
                  <summary>
                    <span>i</span>
                    展示口径
                  </summary>
                  <div className="presentation-readout">
                    <div>
                      <span>这页回答</span>
                      <strong>{presentation.business_question || "这份 YAML1 在表达什么业务判断？"}</strong>
                    </div>
                    <div>
                      <span>展示逻辑</span>
                      <strong>{presentation.display_strategy || "按业务驱动展示。"}</strong>
                    </div>
                    <div>
                      <span>主维度</span>
                      <strong>{presentation.primary_dimension || "业务线"}</strong>
                    </div>
                  </div>
                </details>
              ) : null}
            </div>
            <div className="forecast-highlight">
              <div className="forecast-highlight-title">
                <span>未来三年经营预测</span>
                <strong>{focusYears[0]}E - {focusYears[focusYears.length - 1]}E</strong>
              </div>
              <table>
                <thead>
                  <tr>
                    <th>指标</th>
                    {focusYears.map((year) => (
                      <th key={year}>{year}E</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {forecastRows.map((row) => (
                    <tr key={row.label}>
                      <td>{row.label}</td>
                      {focusYears.map((year) => (
                        <td className="numeric" key={year}>{formatNumber(row.values[year])}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {insightItems.length || riskItems.length ? (
            <section className="presentation-notes">
              {insightItems.length ? (
                <div className="business-read">
                  <div className="eyebrow">Business read</div>
                  <ul>
                    {insightItems.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {riskItems.length ? (
                <aside className="risk-footnote">
                  <div className="eyebrow">Things to review</div>
                  <ul>
                    {riskItems.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </aside>
              ) : null}
            </section>
          ) : null}
        </>
      ) : null}

      {page === "detail" ? (
        <section className="business-card">
        <div className="business-section-heading">
          <div>
            <div className="eyebrow">Company total</div>
            <h2>总收入路径</h2>
          </div>
          <p>先看公司层面是否收敛，再下钻每条业务线。</p>
        </div>
        <div className="table-scroll workbook-scroll">
          <table className="financial-table assumption-table">
            <thead>
              <tr>
                <th>指标</th>
                {columns.map((year) => (
                  <th className="numeric" key={year}>
                    {year}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              <tr className="total">
                <td>营业收入</td>
                <td className="numeric">{formatNumber(view.base_revenue)}</td>
                {view.years.map((year) => (
                  <td className="numeric" key={year}>
                    {formatNumber(view.revenues[year])}
                  </td>
                ))}
              </tr>
              <tr>
                <td>同比增长</td>
                <td className="numeric">-</td>
                {view.years.map((year) => (
                  <td className={`numeric ${view.yoy[year] < 0 ? "negative" : ""}`} key={year}>
                    {formatSignedPercent(view.yoy[year])}
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      </section>
      ) : null}

      {page === "detail" ? (
        <section className="business-card core-breakdown detail-section detail-section-open">
        <div className="business-section-heading">
          <div>
            <div className="eyebrow">Business lines</div>
            <h2>主拆分 · 业务线</h2>
          </div>
          <p>历史收入按 YAML1 原始 series 展示；预测只看未来三年。</p>
        </div>
        <div className="table-scroll workbook-scroll">
          <table className="financial-table assumption-table business-line-table">
            <thead>
              <tr>
                <th>业务线</th>
                <th className="numeric">2024占比</th>
                <th className="numeric">三年CAGR</th>
                {historyYears.map((year) => (
                  <th className="numeric history-year" key={year}>
                    {year}A
                  </th>
                ))}
                {focusYears.map((year) => (
                  <th className="numeric forecast-year" key={year}>
                    {year}E
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {orderedSegments.map((segment) => {
                const segmentThirdYear = focusYears[focusYears.length - 1] ? segment.revenues[focusYears[focusYears.length - 1]] : undefined;
                const segmentCagr = calcCagr(segment.base_revenue, segmentThirdYear, focusYears.length);
                return (
                  <Fragment key={segment.key}>
                    <tr className="segment-main">
                      <td className="statement-label" title={segment.note ?? segment.name}>
                        <span>{segment.name}</span>
                        <small>收入</small>
                      </td>
                      <td className="numeric">{formatPercent(segment.base_revenue / view.base_revenue, 0)}</td>
                      <td className={`numeric ${segmentCagr != null && segmentCagr < 0 ? "negative" : ""}`}>{formatSignedPercent(segmentCagr)}</td>
                      {historyYears.map((year) => (
                        <td className="numeric history-year" key={year}>
                          {formatNumber(segment.history_revenues?.[year] ?? null)}
                        </td>
                      ))}
                      {focusYears.map((year) => (
                        <td className="numeric forecast-year" key={year}>
                          {formatNumber(segment.revenues[year])}
                        </td>
                      ))}
                    </tr>
                    <tr className="segment-metric">
                      <td className="statement-label metric-label">同比增长</td>
                      <td className="numeric">-</td>
                      <td className="numeric">-</td>
                      {historyYears.map((year) => {
                        const historyYoy = yearOverYear(segment.history_revenues, year);
                        return (
                          <td className={`numeric history-year ${historyYoy != null && historyYoy < 0 ? "negative" : ""}`} key={year}>
                            {formatSignedPercent(historyYoy)}
                          </td>
                        );
                      })}
                      {focusYears.map((year) => (
                        <td className={`numeric forecast-year ${segment.yoys[year] < 0 ? "negative" : ""}`} key={year}>
                          {formatSignedPercent(segment.yoys[year])}
                        </td>
                      ))}
                    </tr>
                    <tr className="segment-metric segment-volume">
                      <td className="statement-label metric-label">销量 万吨</td>
                      <td className="numeric">-</td>
                      <td className="numeric">-</td>
                      {historyYears.map((year) => (
                        <td className="numeric history-year" key={year}>
                          {formatNumber(segment.history_volumes?.[year] ?? null, 1)}
                        </td>
                      ))}
                      {focusYears.map((year) => (
                        <td className="numeric forecast-year" key={year}>
                          {formatNumber(segment.volumes?.[year] ?? null, 1)}
                        </td>
                      ))}
                    </tr>
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
      ) : null}
    </div>
  );
}

// ─────────────────────────── Stash type-dispatch view (universal) ───────────────────────────

function isStashBlock(item: unknown): item is StashBlock {
  return typeof item === "object" && item !== null && "type" in item && "name" in item;
}
function isSeriesItem(item: unknown): item is { label: string; values: Record<string, number | null>; note?: string | null } {
  return typeof item === "object" && item !== null && "values" in item && !("type" in item);
}
function isTextItem(item: unknown): item is { label: string; text: string } {
  return typeof item === "object" && item !== null && "text" in item && !("type" in item);
}
function isScalarItem(item: unknown): item is { label: string; value: number | string } {
  return typeof item === "object" && item !== null && "value" in item && !("type" in item);
}

function StashSeriesTable({ items, colLabels }: { items: { label: string; values: Record<string, number | null>; note?: string | null }[]; colLabels?: Record<string, string> | null }) {
  const colSet = new Set<string>();
  items.forEach((it) => Object.keys(it.values).forEach((k) => colSet.add(k)));
  const cols = [...colSet].sort((a, b) => {
    const na = Number(a);
    const nb = Number(b);
    if (!Number.isNaN(na) && !Number.isNaN(nb)) return na - nb;
    return a.localeCompare(b);
  });
  return (
    <div className="table-scroll workbook-scroll">
      <table className="financial-table stash-table">
        <thead>
          <tr className="year-header-row">
            <th>项目</th>
            {cols.map((c) => (
              <th className="numeric" key={c}>{colLabels?.[c] ?? c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {items.map((it, i) => (
            <tr key={i}>
              <td className="statement-label" title={it.note ?? it.label}>{it.label}</td>
              {cols.map((c) => {
                const v = it.values[c];
                return (
                  <td className={`numeric ${typeof v === "number" && v < 0 ? "negative" : ""}`} key={c}>
                    {typeof v === "number" ? formatNumber(v) : ""}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const STASH_TYPE_LABEL: Record<StashBlock["type"], string> = {
  list: "列表",
  series_table: "序列",
  attr_table: "属性",
  text_dict: "文本",
  scalar_table: "标量",
  kv: "其它",
};

const DISPLAY_BADGE_LABELS: Record<string, string> = {
  deprecated: "弃用/复盘",
  check_only: "核对项",
  missing_disclosure: "未披露",
  conflict: "冲突",
  technical: "技术",
};

function StashBlockBody({ block, depth = 0 }: { block: StashBlock; depth?: number }) {
  const seriesItems = block.items.filter(isSeriesItem);
  const textItems = block.items.filter(isTextItem);
  const scalarItems = block.items.filter(isScalarItem);
  return (
    <div className="stash-block-body">
      {block.note ? <p className="stash-note">{block.note}</p> : null}
      {block.caveat ? <p className="stash-caveat">⚠ {block.caveat}</p> : null}
      {block.type === "list" ? (
        <ul className="stash-list">
          {block.items.map((it, i) => (
            <li key={i}>{typeof it === "string" ? it : isTextItem(it) ? it.text : isScalarItem(it) ? it.value : ""}</li>
          ))}
        </ul>
      ) : block.type === "series_table" || block.type === "attr_table" ? (
        <StashSeriesTable items={seriesItems} colLabels={block.col_labels} />
      ) : block.type === "text_dict" ? (
        <div className="stash-text-dict">
          {textItems.map((it, i) => (
            <div className="stash-text-row" key={i}>
              <span className="stash-text-label">{it.label}</span>
              <span className="stash-text-body">{it.text}</span>
            </div>
          ))}
        </div>
      ) : block.type === "scalar_table" ? (
        <div className="stash-scalar-list">
          {scalarItems.map((it, i) => (
            <div className="stash-scalar-row" key={i}>
              <span className="stash-text-label">{it.label}</span>
              <span className="numeric">{typeof it.value === "number" ? formatNumber(it.value) : it.value}</span>
            </div>
          ))}
        </div>
      ) : (
        <div className="stash-kv">
          {block.items.map((it, i) =>
            typeof it === "string" ? (
              <div className="stash-text-row" key={i}><span className="stash-text-body">{it}</span></div>
            ) : isStashBlock(it) ? (
              <StashBlockView block={it} depth={depth + 1} key={i} />
            ) : isTextItem(it) ? (
              <div className="stash-text-row" key={i}><span className="stash-text-label">{it.label}</span><span className="stash-text-body">{it.text}</span></div>
            ) : isScalarItem(it) ? (
              <div className="stash-scalar-row" key={i}><span className="stash-text-label">{it.label}</span><span className="numeric">{typeof it.value === "number" ? formatNumber(it.value) : it.value}</span></div>
            ) : null,
          )}
        </div>
      )}
      {block.extras && block.extras.length > 0 ? (
        <div className="stash-extras">
          {block.extras.map((sub, i) => (
            <StashBlockView block={sub} depth={depth + 1} key={i} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function StashBlockView({ block, depth = 0, display }: { block: StashBlock; depth?: number; display?: DisplayBlock }) {
  const open = block.type === "series_table" || block.type === "attr_table";
  const title = display?.title && display.title !== block.path ? display.title : block.name;
  const badgeKey = display && display.status !== "reference" ? display.status : display?.role;
  const badgeLabel = badgeKey ? DISPLAY_BADGE_LABELS[badgeKey] : "";
  return (
    <details className={`stash-block depth-${depth}`} open={open}>
      <summary className="stash-block-header">
        <span className="stash-block-name">{title}</span>
        <span className="stash-type-badge">{STASH_TYPE_LABEL[block.type]}</span>
        {badgeLabel ? <span className={`stash-display-badge status-${badgeKey}`}>{badgeLabel}</span> : null}
        <span className="stash-block-count">{block.items.length}</span>
        {block.unit ? <span className="stash-unit">{block.unit}</span> : null}
      </summary>
      <StashBlockBody block={block} depth={depth} />
    </details>
  );
}

// 参考项分组：按 compiler 命名约定（非公司身份）把同类 block 收进一个折叠伞，减少视觉块数。
// 约定：name 含「历史」→ 历史观测；含「核对」→ 核对项；含「说明/附注/情报」→ 口径与情报；其余 → 其他参考。
type RefGroup = { key: string; title: string; open: boolean; blocks: StashBlock[] };
const REF_GROUP_DEFS: Array<{ key: string; title: string; open: boolean; match: (name: string) => boolean }> = [
  { key: "history", title: "历史观测（照搬外部模型）", open: true, match: (n) => n.includes("历史") },
  { key: "check", title: "核对项", open: false, match: (n) => n.includes("核对") },
  { key: "notes", title: "口径说明 · 溯源附注 · 定性情报", open: false, match: (n) => n.includes("说明") || n.includes("附注") || n.includes("情报") },
];

function groupRefBlocks(blocks: StashBlock[]): RefGroup[] {
  const groups: RefGroup[] = REF_GROUP_DEFS.map((g) => ({ key: g.key, title: g.title, open: g.open, blocks: [] as StashBlock[] }));
  const rest: StashBlock[] = [];
  for (const b of blocks) {
    const def = REF_GROUP_DEFS.find((gg) => gg.match(b.name));
    if (def) groups.find((g) => g.key === def.key)!.blocks.push(b);
    else rest.push(b);
  }
  const result = groups.filter((g) => g.blocks.length > 0);
  if (rest.length > 0) result.push({ key: "other", title: "其他参考", open: false, blocks: rest });
  return result;
}

function StashGroupView({ title, blocks, defaultOpen }: { title: string; blocks: StashBlock[]; defaultOpen: boolean }) {
  return (
    <details className="stash-group" open={defaultOpen}>
      <summary className="stash-group-header">
        <span className="stash-block-name">{title}</span>
        <span className="stash-block-count">{blocks.length}</span>
      </summary>
      <div className="stash-group-body">
        {blocks.map((b, i) => (
          <div className="stash-subblock" key={i}>
          <h4 className="stash-subblock-title">
            {b.name}
            {b.unit ? <span className="stash-unit">{b.unit}</span> : null}
          </h4>
          <StashBlockBody block={b} />
          </div>
        ))}
      </div>
    </details>
  );
}

function StashView({ blocks }: { blocks: StashBlock[] }) {
  if (!blocks.length) {
    return <EmptyState title="无参考项" body="这份 yaml1 没有 stash 收纳区。" />;
  }
  const groups = groupRefBlocks(blocks);
  return (
    <section className="card stash-view">
      <div className="section-heading">
        <div>
          <div className="eyebrow">③ Reference items · stash</div>
          <h2>参考项（不进 DCF，留作研究）</h2>
          <p>历史观测 / 核对项 / 口径说明 / 溯源附注 / 定性情报 —— 按 yaml1 原始结构展开，无删减。点击标题展开/折叠。</p>
        </div>
        <StatusPill label={`${blocks.length} 块`} />
      </div>
      <div className="stash-blocks">
        {groups.map((g) =>
          g.blocks.length === 1 && g.key === "other" ? (
            <StashBlockView block={g.blocks[0]} key={g.key} />
          ) : (
            <StashGroupView title={g.title} blocks={g.blocks} defaultOpen={g.open} key={g.key} />
          ),
        )}
      </div>
    </section>
  );
}

// ─────────────────────────── Terminal assumptions ───────────────────────────

function TerminalBlock({ terminal }: { terminal: TerminalView }) {
  if (!terminal || terminal.explicit_end == null) return null;
  return (
    <div className="terminal-block">
      <div className="eyebrow">三段式</div>
      <div className="terminal-grid">
        <div><span>显式期末</span><strong>{terminal.explicit_end}</strong></div>
        <div><span>衰减至</span><strong>{terminal.to_year ?? "-"}</strong></div>
        <div><span>衰减方式</span><strong>{terminal.kind ?? "-"}</strong></div>
        <div><span>永续增速</span><strong>{formatPercent(terminal.perpetual_growth ?? 0, 1)}</strong></div>
      </div>
      {terminal.fade_paths && terminal.fade_paths.length ? (
        <div className="terminal-paths"><span className="path-tag-label">fade</span>{terminal.fade_paths.map((p) => <code key={p}>{p}</code>)}</div>
      ) : null}
      {terminal.hold_paths && terminal.hold_paths.length ? (
        <div className="terminal-paths"><span className="path-tag-label">hold</span>{terminal.hold_paths.map((p) => <code key={p}>{p}</code>)}</div>
      ) : null}
    </div>
  );
}

// ─────────────────────────── Valuation bridge ───────────────────────────

function num(d: Record<string, unknown> | null | undefined, key: string): number | null {
  if (!d) return null;
  const v = d[key];
  return typeof v === "number" ? v : null;
}

function ValuationBridge({ dcf, detail }: { dcf: Record<string, unknown> | null | undefined; detail: DcfDetailRow[] }) {
  const pvFcff = num(dcf, "pv_fcff");
  const terminalPv = num(dcf, "terminal_pv");
  const ev = num(dcf, "enterprise_value");
  const netDebt = num(dcf, "net_debt");
  const equity = num(dcf, "equity_value");
  const shares = num(dcf, "total_shares");
  const perShare = num(dcf, "per_share_value");
  if (perShare == null) return null;
  return (
    <section className="card valuation-bridge-card">
      <div className="section-heading">
        <div>
          <div className="eyebrow">How 17.03 is built</div>
          <h2>估值桥</h2>
        </div>
      </div>
      <div className="valuation-bridge">
        <div className="bridge-step"><span className="bridge-label">PV(FCFF)</span><strong>{formatNumber(pvFcff)}</strong></div>
        <span className="bridge-op">+</span>
        <div className="bridge-step"><span className="bridge-label">终值 PV</span><strong>{formatNumber(terminalPv)}</strong></div>
        <span className="bridge-op">=</span>
        <div className="bridge-step bridge-result"><span className="bridge-label">企业价值 EV</span><strong>{formatNumber(ev)}</strong></div>
        <span className="bridge-op">−</span>
        <div className="bridge-step"><span className="bridge-label">净负债</span><strong>{formatNumber(netDebt)}</strong></div>
        <span className="bridge-op">=</span>
        <div className="bridge-step"><span className="bridge-label">权益价值</span><strong>{formatNumber(equity)}</strong></div>
        <span className="bridge-op">÷</span>
        <div className="bridge-step"><span className="bridge-label">总股本</span><strong>{formatNumber(shares)}</strong></div>
        <span className="bridge-op">=</span>
        <div className="bridge-step bridge-final"><span className="bridge-label">每股</span><strong>{formatNumber(perShare, 2)}</strong></div>
      </div>
      {detail.length > 0 ? (
        <div className="fcff-build">
          <div className="eyebrow">FCFF 逐年构建 = NOPAT + 折旧摊销 − Capex − Δ营运资金</div>
          <div className="table-scroll workbook-scroll">
            <table className="financial-table fcff-build-table">
              <thead>
                <tr>
                  <th>年</th>
                  <th className="numeric">NOPAT</th>
                  <th className="numeric">+ DA</th>
                  <th className="numeric">− Capex</th>
                  <th className="numeric">− ΔNWC</th>
                  <th className="numeric">= FCFF</th>
                  <th className="numeric">× 折现</th>
                  <th className="numeric">PV</th>
                </tr>
              </thead>
              <tbody>
                {detail.map((r) => (
                  <tr key={r.period}>
                    <td>{r.period}</td>
                    <td className="numeric">{formatNumber(r.nopat)}</td>
                    <td className="numeric">{formatNumber(r.da)}</td>
                    <td className="numeric">{formatNumber(r.capex)}</td>
                    <td className={`numeric ${r.delta_nwc < 0 ? "negative" : ""}`}>{formatNumber(r.delta_nwc)}</td>
                    <td className="numeric">{formatNumber(r.fcff)}</td>
                    <td className="numeric">{r.discount_factor.toFixed(3)}</td>
                    <td className="numeric">{formatNumber(r.pv_fcff)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
    </section>
  );
}

// ─────────────────────────── Full statement table (history | forecast) ───────────────────────────

const STATEMENT_KEY_ROWS: Record<string, Set<string>> = {
  is: new Set(["revenue", "total_revenue", "operate_profit", "total_profit", "n_income", "n_income_attr_p"]),
  bs: new Set(["money_cap", "total_assets", "total_liab", "total_hldr_eqy_inc_min_int", "total_hldr_eqy_exc_min_int"]),
  cf: new Set(["n_cashflow_act", "n_cashflow_inv_act", "n_cash_flows_fnc_act", "n_incr_cash_cash_equ", "c_cash_equ_end_period"]),
};

const STATEMENT_HIDDEN_ROWS: Record<string, Set<string>> = {
  is: new Set(["total_opcost"]),
};

const STATEMENT_RELOCATE_AFTER: Record<string, Record<string, string>> = {
  bs: {
    accounts_receiv_bill: "accounts_receiv",
    accounts_pay: "acct_payable",
    cip_total: "cip",
    fix_assets_total: "fix_assets",
    long_pay_total: "lt_payable",
    oth_pay_total: "oth_payable",
    oth_rcv_total: "oth_receiv",
  },
};

const QUARTERLY_KEY_ROWS = new Set(["revenue", "oper_cost", "operate_profit", "total_profit", "n_income"]);

type StatementDisplayFormat = "number" | "percent" | "signedPercent";

type StatementDisplayRow = Omit<StatementRow, "role"> & {
  role: StatementRow["role"] | "metric";
  displayFormat?: StatementDisplayFormat;
  synthetic?: boolean;
  categoryStart?: boolean;
  presentationFallback?: boolean;
};

function ratioOrNull(numerator: number | null | undefined, denominator: number | null | undefined): number | null {
  if (typeof numerator !== "number" || typeof denominator !== "number" || !Number.isFinite(numerator) || !Number.isFinite(denominator) || Math.abs(denominator) < 1e-9) {
    return null;
  }
  return numerator / denominator;
}

function calcYoy(values: Record<string, number | null>, years: string[]): Record<string, number | null> {
  return years.reduce<Record<string, number | null>>((acc, year, index) => {
    const current = values[year];
    const previous = index > 0 ? values[years[index - 1]] : null;
    acc[year] = ratioOrNull(typeof current === "number" && typeof previous === "number" ? current - previous : null, previous);
    return acc;
  }, {});
}

function makeMetricRow(
  field: string,
  label: string,
  values: Record<string, number | null>,
  displayFormat: StatementDisplayFormat = "percent",
): StatementDisplayRow {
  return {
    field,
    label,
    category: "metric",
    category_label: "关键比率",
    role: "metric",
    level: 1,
    is_zero: !Object.values(values).some((value) => typeof value === "number" && Math.abs(value) > 1e-9),
    values,
    displayFormat,
    synthetic: true,
  };
}

function derivedAnnualMetricValues(derivedMetrics: DerivedMetrics | null | undefined, metric: string, visibleYears: string[]): Record<string, number | null> | null {
  const annual = derivedMetrics?.annual;
  if (!annual) return null;
  let hasValue = false;
  const values = visibleYears.reduce<Record<string, number | null>>((acc, year) => {
    const value = annual[year]?.[metric];
    acc[year] = typeof value === "number" && Number.isFinite(value) ? value : null;
    if (acc[year] !== null) hasValue = true;
    return acc;
  }, {});
  return hasValue ? values : null;
}

function makeDerivedMetricRow(
  derivedMetrics: DerivedMetrics | null | undefined,
  metric: string,
  field: string,
  label: string,
  visibleYears: string[],
  displayFormat: StatementDisplayFormat = "percent",
): StatementDisplayRow | null {
  const values = derivedAnnualMetricValues(derivedMetrics, metric, visibleYears);
  return values ? makeMetricRow(field, label, values, displayFormat) : null;
}

function hasNonZeroInYears(row: StatementRow | undefined, years: string[]): boolean {
  if (!row) return false;
  return years.some((year) => {
    const value = row.values[year];
    return typeof value === "number" && Number.isFinite(value) && Math.abs(value) > 1e-9;
  });
}

function shouldUseComboFallback(row: StatementRow, rowMap: Map<string, StatementRow>, visibleYears: string[]): boolean {
  if (row.category !== "combo" || !row.combo_of?.length || !hasNonZeroInYears(row, visibleYears)) return false;
  const splitRows = row.combo_of.map((field) => rowMap.get(field)).filter(Boolean) as StatementRow[];
  return !splitRows.length || !splitRows.some((splitRow) => hasNonZeroInYears(splitRow, visibleYears));
}

function buildStatementDisplayRows(sheet: StatementSheet, showZeroRows: boolean, showTechnicalRows: boolean, visibleYears: string[], derivedMetrics?: DerivedMetrics | null): StatementDisplayRow[] {
  const rowMap = new Map(sheet.rows.map((row) => [row.field, row]));
  const hidden = STATEMENT_HIDDEN_ROWS[sheet.key] ?? new Set<string>();
  const relocateAfter = STATEMENT_RELOCATE_AFTER[sheet.key] ?? {};
  const eligibleRows = sheet.rows.filter((row) => !hidden.has(row.field) && (showZeroRows || !row.is_zero || row.role !== "normal"));
  const eligibleFields = new Set(eligibleRows.map((row) => row.field));
  const visibleBaseRows: StatementDisplayRow[] = [];
  const relocatedRows = new Map<string, StatementDisplayRow[]>();
  for (const row of eligibleRows) {
    const fallback = shouldUseComboFallback(row, rowMap, visibleYears);
    if (row.is_technical && !showTechnicalRows && !fallback) continue;
    const displayRow: StatementDisplayRow = {
      ...row,
      label: fallback ? row.display_label ?? row.label : row.label,
      display_role: fallback ? "primary" : row.display_role,
      is_technical: fallback ? false : row.is_technical,
      presentationFallback: fallback,
    };
    const anchor = relocateAfter[row.field];
    if (anchor && eligibleFields.has(anchor)) {
      relocatedRows.set(anchor, [...(relocatedRows.get(anchor) ?? []), displayRow]);
    } else {
      visibleBaseRows.push(displayRow);
    }
  }
  const baseRows = visibleBaseRows.filter((row) => !relocateAfter[row.field] || !eligibleFields.has(relocateAfter[row.field]));
  const metricRowsByAnchor = new Map<string, StatementDisplayRow[]>();

  if (sheet.key === "is") {
    const revenue = rowMap.get("revenue") ?? rowMap.get("total_revenue");
    const operCost = rowMap.get("oper_cost");
    const totalCogs = rowMap.get("total_cogs");
    const operateProfit = rowMap.get("operate_profit");
    const totalProfit = rowMap.get("total_profit");
    const incomeTax = rowMap.get("income_tax");
    const netIncome = rowMap.get("n_income");
    const addMetric = (anchor: string, row: StatementDisplayRow | null | undefined) => {
      if (!row || (!showZeroRows && row.is_zero)) return;
      metricRowsByAnchor.set(anchor, [...(metricRowsByAnchor.get(anchor) ?? []), row]);
    };
    const addDerived = (anchor: string, metric: string, field: string, label: string, displayFormat: StatementDisplayFormat = "percent") => {
      addMetric(anchor, makeDerivedMetricRow(derivedMetrics, metric, field, label, visibleYears, displayFormat));
    };
    if (derivedMetrics?.annual) {
      if (revenue) addDerived(revenue.field, "revenue_yoy", "revenue_yoy_display", "收入同比", "signedPercent");
      if (operCost && revenue) addDerived("oper_cost", "gross_margin", "gross_margin_display", "毛利率");
      addDerived("sell_exp", "sell_exp_rate", "sell_exp_rate_display", "销售费用率");
      addDerived("admin_exp", "admin_exp_rate", "admin_exp_rate_display", "管理费用率");
      addDerived("rd_exp", "rd_exp_rate", "rd_exp_rate_display", "研发费用率");
      addDerived("fin_exp", "fin_exp_rate", "fin_exp_rate_display", "财务费用率");
      if (totalCogs) addDerived("total_cogs", "total_cogs_rate", "total_cogs_rate_display", "营业总成本率");
      if (operateProfit) addDerived("operate_profit", "operate_margin", "operate_margin_display", "营业利润率");
      if (totalProfit) addDerived("total_profit", "total_profit_margin", "total_profit_margin_display", "利润总额率");
      if (incomeTax && totalProfit) addDerived("income_tax", "effective_tax_rate", "income_tax_rate_display", "所得税率");
      if (netIncome) {
        addDerived("n_income", "n_income_margin", "net_margin_display", "净利率");
        addDerived("n_income", "n_income_yoy", "n_income_yoy_display", "净利润同比", "signedPercent");
      }
    } else {
    const revValues = revenue?.values ?? {};
    const ratioToRevenue = (row?: StatementRow) =>
      visibleYears.reduce<Record<string, number | null>>((acc, year) => {
        acc[year] = ratioOrNull(row?.values[year], revValues[year]);
        return acc;
      }, {});
    const derivedMargin = (numerator?: StatementRow, denominator?: StatementRow) =>
      visibleYears.reduce<Record<string, number | null>>((acc, year) => {
        acc[year] = ratioOrNull(numerator?.values[year], denominator?.values[year]);
        return acc;
      }, {});
    if (revenue) addMetric(revenue.field, makeMetricRow("revenue_yoy_display", "收入同比", calcYoy(revenue.values, visibleYears), "signedPercent"));
    if (operCost && revenue) {
      addMetric("oper_cost", makeMetricRow("gross_margin_display", "毛利率", visibleYears.reduce<Record<string, number | null>>((acc, year) => {
        const rev = revenue.values[year];
        const cost = operCost.values[year];
        acc[year] = typeof rev === "number" && typeof cost === "number" ? ratioOrNull(rev - cost, rev) : null;
        return acc;
      }, {})));
    }
    addMetric("sell_exp", makeMetricRow("sell_exp_rate_display", "销售费用率", ratioToRevenue(rowMap.get("sell_exp"))));
    addMetric("admin_exp", makeMetricRow("admin_exp_rate_display", "管理费用率", ratioToRevenue(rowMap.get("admin_exp"))));
    addMetric("rd_exp", makeMetricRow("rd_exp_rate_display", "研发费用率", ratioToRevenue(rowMap.get("rd_exp"))));
    addMetric("fin_exp", makeMetricRow("fin_exp_rate_display", "财务费用率", ratioToRevenue(rowMap.get("fin_exp"))));
    if (totalCogs) addMetric("total_cogs", makeMetricRow("total_cogs_rate_display", "营业总成本率", ratioToRevenue(totalCogs)));
    if (operateProfit) addMetric("operate_profit", makeMetricRow("operate_margin_display", "营业利润率", ratioToRevenue(operateProfit)));
    if (totalProfit) addMetric("total_profit", makeMetricRow("total_profit_margin_display", "利润总额率", ratioToRevenue(totalProfit)));
    if (incomeTax && totalProfit) addMetric("income_tax", makeMetricRow("income_tax_rate_display", "所得税率", derivedMargin(incomeTax, totalProfit)));
    if (netIncome) {
      addMetric("n_income", makeMetricRow("net_margin_display", "净利率", ratioToRevenue(netIncome)));
      addMetric("n_income", makeMetricRow("n_income_yoy_display", "净利润同比", calcYoy(netIncome.values, visibleYears), "signedPercent"));
    }
    }
  }

  const out: StatementDisplayRow[] = [];
  let previousCategory = "";
  for (const row of baseRows) {
    const displayRow: StatementDisplayRow = {
      ...row,
      categoryStart: Boolean(previousCategory && previousCategory !== row.category),
    };
    out.push(displayRow);
    previousCategory = row.category;
    const relocated = relocatedRows.get(row.field) ?? [];
    for (const item of relocated) {
      out.push({
        ...item,
        categoryStart: false,
      });
    }
    const metrics = metricRowsByAnchor.get(row.field) ?? [];
    out.push(...metrics);
  }
  return out;
}

function formatStatementCell(value: number | null | undefined, displayFormat: StatementDisplayFormat = "number"): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "";
  if (displayFormat === "percent") return formatPercent(value, 1);
  if (displayFormat === "signedPercent") return formatSignedPercent(value, 1);
  return formatNumber(value);
}

function FullStatementTable({ sheet, basePeriod, showZeroRows, showTechnicalRows, years, derivedMetrics }: { sheet: StatementSheet; basePeriod: string; showZeroRows: boolean; showTechnicalRows: boolean; years?: string[]; derivedMetrics?: DerivedMetrics | null }) {
  const visibleYears = years ?? sheet.years;
  const historyYears = useMemo(() => {
    const base = Number(basePeriod);
    return new Set(visibleYears.filter((y) => (Number(y) || 0) <= base));
  }, [visibleYears, basePeriod]);
  const rows = useMemo(() => buildStatementDisplayRows(sheet, showZeroRows, showTechnicalRows, visibleYears, derivedMetrics), [sheet, showZeroRows, showTechnicalRows, visibleYears, derivedMetrics]);
  const keyRows = STATEMENT_KEY_ROWS[sheet.key] ?? new Set<string>();
  const yearLabel = (year: string) => (historyYears.has(year) ? year : `${year}E`);
  return (
    <section className="spreadsheet-card statement-card">
      <div className="section-heading compact">
        <div>
          <div className="eyebrow">{sheet.unit} · 历史 + 预测</div>
          <h2>{sheet.title}</h2>
        </div>
        <div className="legend-row">
          <span className="legend-chip history">历史</span>
          <span className="legend-chip forecast">预测 E</span>
        </div>
      </div>
      <div className="table-scroll workbook-scroll">
        <table className="financial-table statement-table full-statement-table">
          <thead>
            <tr className="year-header-row">
              <th>科目</th>
              {visibleYears.map((year) => (
                <th className={`numeric year-th ${historyYears.has(year) ? "history-year" : "forecast-year"}`} key={year}>{yearLabel(year)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr className={`${row.role} level-${row.level} ${keyRows.has(row.field) ? "key-row" : ""} ${row.synthetic ? "metric-row" : ""} ${row.is_technical ? "technical-row" : ""} ${row.presentationFallback ? "fallback-row" : ""} ${row.categoryStart ? "category-start" : ""}`} key={row.field}>
                <td className="statement-label" title={`${row.label} (${row.field})`}><span>{row.label}</span></td>
                {visibleYears.map((year) => {
                  const value = row.values[year];
                  return (
                    <td className={`numeric ${historyYears.has(year) ? "history-year" : "forecast-year"} ${typeof value === "number" && value < 0 ? "negative" : ""}`} key={`${row.field}-${year}`}>
                      {formatStatementCell(value, row.displayFormat)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

// ─────────────────────────── 统一时间轴表（一区一表，列对齐，缺数据留空） ───────────────────────────
// 三个区域各用一张表、一个共享年份轴：所有行共享同一组年份列 → 时间轴严格对齐。
// 没有数据的格子留空（空字符串），不另起表、不另起轴。

type AxisRow = {
  label: string;
  values: Record<string, number | null>;
  note?: string | null;
  bold?: boolean;
  override?: boolean;
  muted?: boolean;
  driver?: boolean;
  editablePath?: string;
  // int=整数金额(百万元) · num2=2位小数(参考项通用) · decimal=小数比率×100+%(旋钮) ·
  // percent1=无符号百分比1位 · signedDecimal=带符号同比% · volume=1位小数(万吨)
  format?: "int" | "num2" | "decimal" | "decimal1" | "percent1" | "signedDecimal" | "volume";
};

type AssumptionInlineEdit = {
  pointer: string;
  raw: string;
};
type AxisGroup = {
  title: string;
  unit?: string | null;
  caveat?: string | null;
  note?: string | null;
  rows: AxisRow[];
};

const isYearKeyStr = (k: string) => /^\d{4}$/.test(k) && Number(k) > 1900 && Number(k) < 2100;

function formatAxisCell(v: number | null | undefined, format: AxisRow["format"]): string {
  if (typeof v !== "number" || Number.isNaN(v)) return "";
  switch (format) {
    case "decimal":
      return formatPercent(v, 2);
    case "decimal1":
      return formatPercent(v, 1);
    case "percent1":
      return formatPercent(v, 1);
    case "signedDecimal":
      return formatSignedPercent(v, 1);
    case "num2":
      return formatNumber(v, 2);
    case "volume":
      return formatNumber(v, 1);
    default:
      return formatNumber(v);
  }
}

function humanizeUnit(u?: string | null): string {
  if (!u) return "";
  const s = u.trim();
  if (s === "pct" || s === "%") return "%";
  if (s.includes("100mn")) return `亿元${s.includes("存疑") ? " · 存疑" : ""}`;
  if (s.includes("cny_per_ton")) return "元/吨";
  if (s.includes("million") || s.includes("cny")) return "百万元";
  return s;
}

function yearLabel(y: string, baseYear: number): string {
  return Number(y) > baseYear ? `${y}E` : y;
}

function unionYears(sets: Array<Iterable<string> | undefined | null>): string[] {
  const s = new Set<string>();
  for (const set of sets) {
    if (!set) continue;
    for (const y of set) if (isYearKeyStr(String(y))) s.add(String(y));
  }
  return [...s].sort((a, b) => Number(a) - Number(b));
}

// 历史序列 → {年: yoy}（有前年才算）；容忍 null 值
function yoySeries(history: Record<string, number | null> | undefined): Record<string, number | null> {
  const out: Record<string, number | null> = {};
  if (!history) return out;
  const clean: Record<string, number> = {};
  for (const [k, v] of Object.entries(history)) {
    if (typeof v === "number") clean[k] = v;
  }
  for (const y of Object.keys(clean)) {
    if (!isYearKeyStr(y)) continue;
    out[y] = yearOverYear(clean, y);
  }
  return out;
}

function ratioSeries(
  numerator: Record<string, number | null> | undefined,
  denominator: Record<string, number | null> | undefined,
): Record<string, number | null> {
  const values: Record<string, number | null> = {};
  const years = unionYears([Object.keys(numerator ?? {}), Object.keys(denominator ?? {})]);
  for (const year of years) {
    const n = numerator?.[year];
    const d = denominator?.[year];
    values[year] = typeof n === "number" && typeof d === "number" && d !== 0 ? n / d : null;
  }
  return values;
}

function normalizeBusinessLabel(value: string): string {
  return value.replace(/[（）()及与和、/\\\s·_\-:：]/g, "").toLowerCase();
}

function matchRevenueSegment(label: string, segments: Yaml1RevenueSegment[]): Yaml1RevenueSegment | null {
  const target = normalizeBusinessLabel(label);
  if (!target) return null;
  const scored = segments
    .map((segment) => {
      const names = [segment.name, segment.key].map((item) => normalizeBusinessLabel(String(item))).filter(Boolean);
      const matched = names.some((name) => target === name);
      const score = matched ? Math.max(...names.map((name) => name.length)) : 0;
      return { segment, score };
    })
    .filter((item) => item.score > 0)
    .sort((a, b) => b.score - a.score);
  return scored[0]?.segment ?? null;
}

function seriesEquivalentOnSharedYears(
  candidate: Record<string, number | null> | undefined,
  baseline: Record<string, number | null> | undefined,
  tolerance = 0.5,
): boolean {
  if (!candidate || !baseline) return false;
  const years = Object.keys(candidate).filter((year) => typeof candidate[year] === "number" && typeof baseline[year] === "number");
  if (!years.length) return false;
  return years.every((year) => Math.abs((candidate[year] as number) - (baseline[year] as number)) <= tolerance);
}

function stashPath(block: StashBlock): string {
  return block.path || `stash.${block.name}`;
}

function displayBlockMap(contract?: Yaml1DisplayContract | null): Map<string, DisplayBlock> {
  return new Map((contract?.blocks ?? []).filter((block) => block.path).map((block) => [block.path, block]));
}

function displayWarningsByPath(contract?: Yaml1DisplayContract | null): Map<string, DisplayWarning[]> {
  const map = new Map<string, DisplayWarning[]>();
  for (const warning of contract?.warnings ?? []) {
    const path = warning.path || "";
    if (!path) continue;
    const rows = map.get(path) ?? [];
    rows.push(warning);
    map.set(path, rows);
  }
  return map;
}

function displayForStash(block: StashBlock, blocks: Map<string, DisplayBlock>): DisplayBlock | undefined {
  return blocks.get(stashPath(block));
}

function displayMetricLabel(metric?: string | null): string | null {
  switch (metric) {
    case "revenue":
      return "收入";
    case "yoy":
      return "同比";
    case "gross_margin":
      return "毛利率";
    case "cost":
      return "成本";
    case "volume":
      return "销量";
    case "price":
      return "价格";
    case "rate":
      return "比率";
    case "amount":
      return "金额";
    default:
      return null;
  }
}

function segmentAttachedFormat(block: StashBlock, display?: DisplayBlock): AxisRow["format"] {
  if (display?.metric === "gross_margin" || display?.metric === "rate" || display?.metric === "yoy") return display.metric === "yoy" ? "signedDecimal" : "percent1";
  if (display?.metric === "revenue" || display?.metric === "cost" || display?.metric === "amount") return "int";
  if (display?.metric === "volume") return "volume";
  const text = `${block.name} ${block.unit ?? ""}`.toLowerCase();
  if (/率|占比|ratio|pct|margin|%/.test(text)) return "percent1";
  if (/收入|成本|金额|百万元|million|cny/.test(text)) return "int";
  if (/销量|volume|万吨/.test(text)) return "volume";
  return "num2";
}

function segmentAttachedMetricLabel(block: StashBlock, display?: DisplayBlock): string {
  const declared = displayMetricLabel(display?.metric);
  if (declared && declared !== "收入") return declared;
  const name = block.name
    .replace(/^分线[_\s-]?/, "")
    .replace(/^业务线[_\s-]?/, "")
    .replace(/历史观测/g, "")
    .replace(/参考/g, "")
    .replace(/ratio|pct|series/gi, "")
    .trim();
  return name || block.name;
}

function attachableSegmentBlock(block: StashBlock, segments: Yaml1RevenueSegment[]): boolean {
  if (!blockIsYearSeries(block)) return false;
  const items = block.items.filter(isSeriesItem);
  if (!items.length) return false;
  const matched = items.filter((item) => matchRevenueSegment(item.label, segments));
  if (!matched.length) return false;
  if (matched.length === items.length) return true;
  if (block.name.includes("副拆分")) return false;
  return /分线|业务线/.test(block.name) && matched.length / items.length >= 0.8;
}

// 一个 stash block 是否为纯年份序列表（值键全为年份）→ 可并入统一年份轴表
function blockIsYearSeries(block: StashBlock): boolean {
  if (block.type !== "series_table" && block.type !== "attr_table") return false;
  const items = block.items.filter(isSeriesItem);
  if (!items.length) return false;
  for (const it of items) {
    for (const k of Object.keys(it.values)) {
      if (!isYearKeyStr(k)) return false;
    }
  }
  return true;
}

function stashBlockYears(block: StashBlock): string[] {
  const years = new Set<string>();
  for (const item of block.items.filter(isSeriesItem)) {
    for (const key of Object.keys(item.values)) {
      const year = key.match(/^(\d{4})/)?.[1];
      if (year && isYearKeyStr(year)) years.add(year);
    }
  }
  return [...years];
}

function UnifiedYearTable({
  years,
  baseYear,
  groups,
  editMode = false,
  editableByPath,
  editablePeriods: editablePeriodSet,
  drafts = {},
  inlineEdit,
  onInlineEditChange,
  onStartInlineEdit,
  onCommitInlineEdit,
  onCancelInlineEdit,
}: {
  years: string[];
  baseYear: number;
  groups: AxisGroup[];
  editMode?: boolean;
  editableByPath?: Map<string, EditableAssumption>;
  editablePeriods?: Set<string>;
  drafts?: Record<string, number | null>;
  inlineEdit?: AssumptionInlineEdit | null;
  onInlineEditChange?: (raw: string) => void;
  onStartInlineEdit?: (assumption: EditableAssumption, cell: EditableAssumptionCell) => void;
  onCommitInlineEdit?: (assumption: EditableAssumption, cell: EditableAssumptionCell) => void;
  onCancelInlineEdit?: () => void;
}) {
  const periodClass = (year: string) => {
    const numericYear = Number(year);
    if (!baseYear || Number.isNaN(numericYear)) return "";
    const role = numericYear > baseYear ? "forecast-year" : "history-year";
    const start = numericYear > baseYear && !years.some((candidate) => {
      const candidateYear = Number(candidate);
      return !Number.isNaN(candidateYear) && candidateYear > baseYear && candidateYear < numericYear;
    });
    return `${role}${start ? " forecast-start" : ""}`;
  };
  const editableCell = (row: AxisRow, year: string) => {
    if (!row.editablePath || !editableByPath) return null;
    const assumption = editableByPath.get(row.editablePath);
    if (!assumption) return null;
    const cell = editableCellForPeriod(assumption, year);
    return cell ? { assumption, cell } : null;
  };

  return (
    <div className="table-scroll workbook-scroll">
      <table className="financial-table unified-table">
        <thead>
          <tr className="year-header-row">
            <th>项目</th>
            {years.map((y) => (
              <th className={`numeric ${periodClass(y)} ${editMode && editablePeriodSet?.has(y) ? "editable-period-head" : ""}`} key={y}>{yearLabel(y, baseYear)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {groups.map((g, gi) => (
            <Fragment key={gi}>
              <tr className="group-header-row">
                <th colSpan={years.length + 1}>
                  <span className="group-title">{g.title}</span>
                  {g.unit ? <span className="axis-unit">{humanizeUnit(g.unit)}</span> : null}
                </th>
              </tr>
              {g.note ? (
                <tr className="group-note-row">
                  <td colSpan={years.length + 1}>{g.note}</td>
                </tr>
              ) : null}
              {g.caveat ? (
                <tr className="group-note-row caveat">
                  <td colSpan={years.length + 1}>⚠ {g.caveat}</td>
                </tr>
              ) : null}
              {g.rows.map((r, ri) => {
                const rowHasEditable = editMode && years.some((y) => Boolean(editableCell(r, y)));
                return (
                <tr key={ri} className={`${r.bold ? "key-row" : ""} ${r.muted ? "muted-row" : ""} ${r.driver ? "driver-assumption-row" : ""} ${rowHasEditable ? "editable-assumption-row" : ""}`}>
                  <td className="statement-label" title={r.note ?? r.label}>
                    {r.override ? <span className="override-dot" title="主动覆盖 / 查证" /> : null}
                    {r.label}
                  </td>
                  {years.map((y) => {
                    const v = r.values[y];
                    const editable = editMode ? editableCell(r, y) : null;
                    const currentValue = editable ? editableValueForCell(editable.cell, drafts) : v;
                    const changed = editable ? editableCellChanged(editable.cell, drafts) : false;
                    const isInline = Boolean(editable && inlineEdit?.pointer === editable.cell.pointer);
                    return (
                      <td
                        className={`numeric ${periodClass(y)} ${typeof currentValue === "number" && currentValue < 0 ? "negative" : ""} ${editable ? "assumption-editable-cell" : ""} ${changed ? "assumption-cell-changed" : ""}`}
                        key={y}
                        onClick={editable && !isInline ? () => onStartInlineEdit?.(editable.assumption, editable.cell) : undefined}
                      >
                        {editable && isInline ? (
                          <div className="assumption-inline-editor">
                            <input
                              autoFocus
                              onBlur={(event) => {
                                if (event.currentTarget.dataset.cancel === "true") return;
                                onCommitInlineEdit?.(editable.assumption, editable.cell);
                              }}
                              onChange={(event) => onInlineEditChange?.(event.currentTarget.value)}
                              onKeyDown={(event) => {
                                if (event.key === "Enter") onCommitInlineEdit?.(editable.assumption, editable.cell);
                                if (event.key === "Escape") {
                                  event.currentTarget.dataset.cancel = "true";
                                  onCancelInlineEdit?.();
                                }
                              }}
                              type="text"
                              value={inlineEdit?.raw ?? ""}
                            />
                          </div>
                        ) : editable ? (
                          <button
                            className={`assumption-inline-cell ${changed ? "is-manual" : ""}`}
                            onClick={(event) => {
                              event.stopPropagation();
                              onStartInlineEdit?.(editable.assumption, editable.cell);
                            }}
                            type="button"
                          >
                            {editableDisplayValue(editable.assumption, currentValue)}
                          </button>
                        ) : (
                          formatAxisCell(v, r.format)
                        )}
                      </td>
                    );
                  })}
                </tr>
                );
              })}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── 区域分组构建器 ──

function displayKnobLabel(label: string, path: string): string {
  const cleaned = label.replace(/^#/, "").replace(/\(.*\)$/, "").replace(/^(减|加):/, "").trim() || path;
  if (path.startsWith("income.cost_rates.") && !cleaned.endsWith("率")) return `${cleaned}率`;
  return cleaned;
}

function knobLabel(k: AssumptionsKnob): string {
  return displayKnobLabel(k.src, k.path);
}
function knobIsRate(path: string): boolean {
  return path.includes("gpm") || path.includes("cost_rates") || path.includes("tax_rate") || path.includes("minority");
}

function statementValueFromPreview(
  baseSheet: StatementSheet | undefined,
  previewSheet: StatementSheet | undefined,
  fields: string[],
  year: string,
  baseYear: number,
): number | null {
  const isForecast = Number(year) > baseYear;
  if (isForecast) {
    const preview = statementValue(previewSheet, fields, year);
    if (preview != null) return preview;
  }
  return statementValue(baseSheet, fields, year);
}

function profitRowsForRevenueBlock(
  baseSheet: StatementSheet | undefined,
  previewSheet: StatementSheet | undefined,
  years: string[],
  baseYear: number,
  revenueValues: Record<string, number | null>,
): AxisRow[] {
  const netIncome: Record<string, number | null> = {};
  const attrNetIncome: Record<string, number | null> = {};
  for (const year of years) {
    netIncome[year] = statementValueFromPreview(baseSheet, previewSheet, ["n_income"], year, baseYear);
    attrNetIncome[year] = statementValueFromPreview(baseSheet, previewSheet, ["n_income_attr_p"], year, baseYear);
  }
  const netMargin: Record<string, number | null> = {};
  for (const year of years) {
    const income = netIncome[year];
    const revenue = revenueValues[year];
    netMargin[year] = typeof income === "number" && typeof revenue === "number" && revenue !== 0 ? income / revenue : null;
  }
  return [
    { label: "归母净利润", bold: true, values: attrNetIncome, format: "int" },
    { label: "净利润", values: netIncome, format: "int" },
    { label: "净利率", muted: true, values: netMargin, format: "decimal" },
    { label: "净利润同比", muted: true, values: yoySeries(netIncome), format: "signedDecimal" },
  ];
}

function historicalAssumptionValues(path: string, sheet: StatementSheet | undefined, baseYear: number): Record<string, number | null> {
  const values: Record<string, number | null> = {};
  if (!sheet || !baseYear) return values;
  const pathParts = path.split(".");
  const directField = path.startsWith("income.") ? pathParts[pathParts.length - 1] : null;
  for (const year of sheet.years) {
    if (Number(year) > baseYear) continue;
    const revenue = statementValue(sheet, ["revenue", "total_revenue"], year);

    if (path === "income.gpm") {
      const cost = statementValue(sheet, ["oper_cost"], year);
      values[year] = typeof revenue === "number" && revenue !== 0 && typeof cost === "number" ? (revenue - cost) / revenue : null;
      continue;
    }

    if (path.startsWith("income.cost_rates.")) {
      const field = path.slice("income.cost_rates.".length);
      const cost = statementValue(sheet, [field], year);
      values[year] = typeof revenue === "number" && revenue !== 0 && typeof cost === "number" ? cost / revenue : null;
      continue;
    }

    if (path === "income.effective_tax_rate") {
      const tax = statementValue(sheet, ["income_tax"], year);
      const profit = statementValue(sheet, ["total_profit"], year);
      values[year] = typeof tax === "number" && typeof profit === "number" && profit !== 0 ? tax / profit : null;
      continue;
    }

    if (path === "income.minority_ratio") {
      const minority = statementValue(sheet, ["minority_gain"], year);
      const netIncome = statementValue(sheet, ["n_income"], year);
      values[year] = typeof minority === "number" && typeof netIncome === "number" && netIncome !== 0 ? minority / netIncome : null;
      continue;
    }

    if (directField) {
      values[year] = statementValue(sheet, [directField], year);
    }
  }
  return values;
}

const REVENUE_DRIVER_LABELS: Record<string, string> = {
  volume: "销量增速",
  price: "吨价增速",
  revenue_yoy: "营收增速",
  margin: "毛利率",
};

// 只有量价族才有"销量"概念；growth/abs 族不应出现销量行（避免乳业"万吨"残留硬编码到服装等公司）。
const VOLUME_FAMILIES = new Set(["factor_product", "vol_price", "vol_price_margin", "driver_rate"]);
// 销量单位从 leaf base.unit.volume 通用映射，不硬编码"万吨"。
const VOLUME_UNIT_LABELS: Record<string, string> = {
  "10k_ton": "万吨",
  ton: "吨",
  "10k_unit": "万件",
  unit: "件",
};

function revenueDriversForSegment(editable: EditableAssumption[], segmentKey: string): EditableAssumption[] {
  const prefix = `income.revenue.${segmentKey}.`;
  const rank: Record<string, number> = { revenue_yoy: 0, volume: 1, price: 2, margin: 3 };
  return editable
    .filter((row) => row.group === "revenue_driver" && row.path.startsWith(prefix))
    .sort((a, b) => (rank[revenueDriverKey(a, segmentKey)] ?? 99) - (rank[revenueDriverKey(b, segmentKey)] ?? 99) || a.label.localeCompare(b.label, "zh-Hans-CN"));
}

function revenueDriverKey(row: EditableAssumption, segmentKey: string): string {
  const prefix = `income.revenue.${segmentKey}.`;
  return row.path.startsWith(prefix) ? row.path.slice(prefix.length) : (row.family ?? "");
}

function revenueDriverAxisRow(row: EditableAssumption, segmentKey: string, segmentName: string): AxisRow {
  const values: Record<string, number | null> = {};
  for (const cell of row.cells) values[cell.year] = cell.value;
  const key = revenueDriverKey(row, segmentKey);
  const label = REVENUE_DRIVER_LABELS[key] ?? row.label.replace(`${segmentName} · `, "");
  return {
    label: `${segmentName} · ${label}`,
    values,
    note: [row.path, row.src, row.note].filter(Boolean).join("\n"),
    muted: true,
    driver: true,
    editablePath: row.path,
    format: editableIsGrowth(row) ? "decimal1" : editableAxisFormat(row),
  };
}

function metricFromAttrKey(key: string): { label: string; format: AxisRow["format"] } {
  const raw = key.replace(/^\d{4}[_-]?/, "").toLowerCase();
  if (/gpm|gross_margin|margin|毛利/.test(raw)) return { label: "毛利率", format: "percent1" };
  if (/yoy|同比/.test(raw)) return { label: "同比", format: "signedDecimal" };
  if (/ton_cost|unit_cost|吨成本/.test(raw)) return { label: "吨成本", format: "num2" };
  if (/cost|成本/.test(raw)) return { label: "成本", format: "int" };
  if (/price|吨价|单价/.test(raw)) return { label: "价格", format: "num2" };
  if (/volume|销量/.test(raw)) return { label: "销量", format: "volume" };
  return { label: raw || key, format: "num2" };
}

function normalizeAttachedValue(value: number | null | undefined, format: AxisRow["format"], unit?: string | null): number | null {
  if (typeof value !== "number") return null;
  if ((format === "percent1" || format === "decimal" || format === "decimal1" || format === "signedDecimal") && Math.abs(value) > 1 && /pct|%/.test(unit ?? "")) {
    return value / 100;
  }
  return value;
}

function segmentAttachedRowsFromStash(segment: Yaml1RevenueSegment, blocks: StashBlock[], skipMetrics: Set<string> = new Set(), displayBlocks: Map<string, DisplayBlock> = new Map()): AxisRow[] {
  const rows: AxisRow[] = [];
  const seen = new Set<string>();
  const segmentRevenueValues: Record<string, number | null> = { ...(segment.history_revenues ?? {}), ...segment.revenues };
  for (const block of blocks) {
    const blockDisplay = displayForStash(block, displayBlocks);
    const sources = [block, ...(block.extras ?? [])].filter(blockIsYearSeries);
    for (const source of sources) {
      const sourceDisplay = displayForStash(source, displayBlocks) ?? blockDisplay;
      const metric = segmentAttachedMetricLabel(source, sourceDisplay);
      if (skipMetrics.has(metric)) continue;
      const format = segmentAttachedFormat(source, sourceDisplay);
      for (const item of source.items.filter(isSeriesItem)) {
        const matched = matchRevenueSegment(item.label, [segment]);
        if (!matched) continue;
        if (source === block && seriesEquivalentOnSharedYears(item.values, segmentRevenueValues)) continue;
        const key = `${metric}:${JSON.stringify(item.values)}`;
        if (seen.has(key)) continue;
        seen.add(key);
        rows.push({
          label: `${segment.name} · ${metric}`,
          values: item.values,
          note: [block.note, source.note, item.note].filter(Boolean).join("\n"),
          muted: true,
          format,
        });
      }
    }
    if (block.type === "attr_table") {
      const rowsByMetric = new Map<string, AxisRow>();
      for (const item of block.items.filter(isSeriesItem)) {
        const matched = matchRevenueSegment(item.label, [segment]);
        if (!matched) continue;
        for (const [key, rawValue] of Object.entries(item.values)) {
          const year = key.match(/^(\d{4})/)?.[1];
          if (!year) continue;
          const metric = metricFromAttrKey(key);
          if (skipMetrics.has(metric.label)) continue;
          const rowKey = `${segment.name}:${metric.label}`;
          const row = rowsByMetric.get(rowKey) ?? {
            label: `${segment.name} · ${metric.label}`,
            values: {},
            note: [block.note, item.note].filter(Boolean).join("\n"),
            muted: true,
            format: metric.format,
          };
          row.values[year] = normalizeAttachedValue(rawValue, metric.format, block.unit);
          rowsByMetric.set(rowKey, row);
        }
      }
      for (const [key, row] of rowsByMetric) {
        if (seen.has(key)) continue;
        seen.add(key);
        rows.push(row);
      }
    }
  }
  return rows;
}

function buildRevenueGroups(
  view: Yaml1RevenueView,
  presentation: Yaml1Presentation | null | undefined,
  secondaryBlocks: StashBlock[],
  segmentAttachedBlocks: StashBlock[] = [],
  displayBlocks: Map<string, DisplayBlock> = new Map(),
  displayWarnings: Map<string, DisplayWarning[]> = new Map(),
  editable: EditableAssumption[] = [],
  fullStatementSheets?: StatementSheet[],
  previewStatementSheets?: StatementSheet[],
): AxisGroup[] {
  const groups: AxisGroup[] = [];
  // 总收入：历史从完整 IS 表 revenue 补全，base+预测来自 revenueView，拼成完整时间轴
  const fullIs = fullStatementSheets?.find((s) => s.key === "is");
  const previewIs = previewStatementSheets?.find((s) => s.key === "is");
  const totalValues: Record<string, number | null> = {};
  if (fullIs) {
    for (const y of fullIs.years) {
      if (Number(y) <= view.base_year) totalValues[y] = statementValue(fullIs, ["revenue"], y);
    }
  }
  totalValues[String(view.base_year)] = view.base_revenue;
  for (const y of view.years) totalValues[y] = statementValue(previewIs, ["revenue"], y) ?? view.revenues[y] ?? null;
  const totalYoy: Record<string, number | null> = yoySeries(totalValues);
  const totalRows: AxisRow[] = [
    { label: "营业收入", bold: true, values: totalValues, format: "int" },
    { label: "同比增长", muted: true, values: totalYoy, format: "signedDecimal" },
    ...profitRowsForRevenueBlock(fullIs, previewIs, unionYears([Object.keys(totalValues), view.years]), view.base_year, totalValues),
  ];
  groups.push({
    title: "总收入与利润路径",
    unit: "百万元",
    rows: totalRows,
  });
  // 主拆分 · 业务线
  const wanted = presentation?.segment_order ?? [];
  const orderedSegments = wanted.length
    ? [...view.segments].sort((a, b) => {
        const ra = wanted.indexOf(a.name);
        const rb = wanted.indexOf(b.name);
        return (ra < 0 ? Number.MAX_SAFE_INTEGER : ra) - (rb < 0 ? Number.MAX_SAFE_INTEGER : rb);
      })
    : view.segments;
  const segRows: AxisRow[] = [];
  for (const seg of orderedSegments) {
    const segmentDrivers = revenueDriversForSegment(editable, seg.key);
    const revenueYoyDriver = segmentDrivers.find((row) => revenueDriverKey(row, seg.key) === "revenue_yoy");
    // abs 族用 revenue_abs 作为可编辑收入输入（收入行可编辑）；growth 族用 revenue_yoy 作为可编辑同比输入。
    // 两者都不进 inlineDriverRows，避免与收入/同比行重复显示。
    const revenueAbsDriver = segmentDrivers.find((row) => revenueDriverKey(row, seg.key) === "revenue_abs");
    const inlineDriverRows = segmentDrivers.filter((row) => row !== revenueYoyDriver && row !== revenueAbsDriver);
    const revValues: Record<string, number | null> = { ...(seg.history_revenues ?? {}), ...seg.revenues };
    segRows.push({ label: `${seg.name} · 收入`, values: revValues, note: seg.note, format: "int", editablePath: revenueAbsDriver?.path });
    const yoyValues: Record<string, number | null> = { ...yoySeries(seg.history_revenues), ...seg.yoys };
    if (revenueYoyDriver) {
      for (const cell of revenueYoyDriver.cells) yoyValues[cell.year] = cell.value;
    }
    segRows.push({ label: `${seg.name} · 同比`, muted: true, values: yoyValues, format: "signedDecimal", editablePath: revenueYoyDriver?.path });
    if (seg.history_costs && Object.keys(seg.history_costs).length > 0) {
      segRows.push({ label: `${seg.name} · 成本`, muted: true, values: seg.history_costs, format: "int" });
      segRows.push({
        label: `${seg.name} · 毛利率`,
        muted: true,
        values: ratioSeries(
          Object.fromEntries(Object.entries(seg.history_costs).map(([year, cost]) => {
            const revenue = seg.history_revenues?.[year];
            return [year, typeof revenue === "number" && typeof cost === "number" ? revenue - cost : null];
          })),
          seg.history_revenues,
        ),
        format: "percent1",
      });
    }
    const derivedMetrics = new Set<string>();
    if (seg.history_costs && Object.keys(seg.history_costs).length > 0) derivedMetrics.add("毛利率");
    for (const row of segmentAttachedRowsFromStash(seg, segmentAttachedBlocks, derivedMetrics, displayBlocks)) {
      segRows.push(row);
    }
    if (VOLUME_FAMILIES.has(seg.family)) {
      const volValues: Record<string, number | null> = { ...(seg.history_volumes ?? {}), ...(seg.volumes ?? {}) };
      const volUnit = VOLUME_UNIT_LABELS[seg.volume_unit ?? ""] ?? "销量";
      segRows.push({ label: `${seg.name} · 销量(${volUnit})`, muted: true, values: volValues, format: "volume" });
    }
    for (const driver of inlineDriverRows) {
      segRows.push(revenueDriverAxisRow(driver, seg.key, seg.name));
    }
  }
  groups.push({ title: "主拆分 · 业务线", unit: "百万元", rows: segRows });
  // 副拆分：收入行 + 可选毛利率/同比行（来自同块 extras 里的"毛利率"/"同比" series 子块）
  for (const b of secondaryBlocks) {
    const display = displayForStash(b, displayBlocks);
    const sub = (display?.title || b.name.replace(/^副拆分[_]?/, "") || b.name).replace(/^副拆分\s*·\s*/, "");
    const gmItems = b.extras?.find((e) => e.name.includes("毛利率"))?.items.filter(isSeriesItem) ?? [];
    const yoyItems = b.extras?.find((e) => e.name.includes("同比"))?.items.filter(isSeriesItem) ?? [];
    const gmMap = new Map(gmItems.map((it) => [it.label, it.values]));
    const yoyMap = new Map(yoyItems.map((it) => [it.label, it.values]));
    const rows: AxisRow[] = [];
    const warnings = displayWarnings.get(stashPath(b)) ?? [];
    const warningText = warnings.map((warning) => warning.message).join("\n");
    for (const it of b.items.filter(isSeriesItem)) {
      rows.push({ label: `${it.label} · 收入`, values: it.values, note: it.note, format: "int" });
      const gm = gmMap.get(it.label);
      if (gm) rows.push({ label: `${it.label} · 毛利率`, values: gm, muted: true, format: "decimal" });
      const yy = yoyMap.get(it.label);
      if (yy) rows.push({ label: `${it.label} · 同比`, values: yy, muted: true, format: "signedDecimal" });
    }
    groups.push({
      title: `副拆分 · ${sub}`,
      unit: b.unit,
      caveat: [b.caveat, warningText].filter(Boolean).join("\n"),
      note: b.note,
      rows,
    });
  }
  return groups;
}

function buildAssumptionsGroups(view: Yaml1AssumptionsView, fullStatementSheets?: StatementSheet[]): AxisGroup[] {
  const fullIs = fullStatementSheets?.find((s) => s.key === "is");
  const baseYear = Number(view.base_period);
  return view.sections.map((sec) => ({
    title: sec.title,
    rows: sec.knobs.map((k) => {
      const values: Record<string, number | null> = historicalAssumptionValues(k.path, fullIs, baseYear);
      view.years.forEach((y, i) => { values[y] = k.values[i] ?? null; });
      return { label: knobLabel(k), values, note: k.note, override: k.is_override, bold: k.is_override, editablePath: k.path, format: knobIsRate(k.path) ? "decimal" : "int" };
    }),
  }));
}

const EDITABLE_GROUP_LABELS: Record<EditableAssumption["group"], string> = {
  result: "结果目标",
  revenue_driver: "收入拆分 drivers",
  standard_knob: "利润表 knobs",
  terminal: "终值 / 时间轴",
  other: "其他覆盖",
};

function editableYears(rows: EditableAssumption[]): string[] {
  return unionYears([rows.flatMap((row) => row.cells.map((cell) => cell.year))]);
}

function editableOriginalValue(row: EditableAssumption, year: string): number | null {
  const cell = row.cells.find((item) => item.year === year);
  return cell?.value ?? null;
}

function editablePointer(row: EditableAssumption, year: string): string | null {
  const cell = row.cells.find((item) => item.year === year);
  return cell?.pointer ?? null;
}

function editableDisplayValue(row: EditableAssumption, value: number | null): string {
  if (value == null) return "";
  if (editableIsPercent(row)) return formatPercent(value, editableIsGrowth(row) ? 1 : 2);
  if (row.format === "integer") return formatNumber(value, 0);
  return formatNumber(value, 2);
}

function editableInputValue(row: EditableAssumption, value: number | null): string {
  if (value == null) return "";
  const displayValue = editableIsPercent(row) ? value * 100 : value;
  return `${Number(displayValue.toFixed(6))}`;
}

function parseEditableInput(row: EditableAssumption, raw: string): number | null {
  const trimmed = raw.trim();
  if (trimmed === "") return null;
  const parsed = Number(trimmed.replace(/,/g, "").replace(/%$/, ""));
  if (!Number.isFinite(parsed)) return null;
  return editableIsPercent(row) ? parsed / 100 : parsed;
}

function editableCellForPeriod(row: EditableAssumption, period: string): EditableAssumptionCell | undefined {
  return row.cells.find((item) => item.year === period);
}

function editableValueForCell(cell: EditableAssumptionCell, drafts: Record<string, number | null>): number | null {
  return cell.pointer in drafts ? drafts[cell.pointer] : cell.value;
}

function editableCellChanged(cell: EditableAssumptionCell, drafts: Record<string, number | null>): boolean {
  return cell.pointer in drafts && drafts[cell.pointer] !== cell.value;
}

function editableRowsByPath(rows: EditableAssumption[]): Map<string, EditableAssumption> {
  return new Map(rows.map((row) => [row.path, row]));
}

function editablePeriods(rows: EditableAssumption[]): string[] {
  return unionYears([rows.filter((row) => row.group !== "terminal").flatMap((row) => row.cells.map((cell) => cell.year))]);
}

function editableAxisFormat(row: EditableAssumption): AxisRow["format"] {
  if (editableIsPercent(row)) return "decimal";
  if (row.format === "integer") return "int";
  return "num2";
}

function editableIsPercent(row: EditableAssumption): boolean {
  return row.format === "percent" || row.unit === "pct" || row.family === "yoy";
}

function editableIsGrowth(row: EditableAssumption): boolean {
  return row.family === "yoy" || row.path.endsWith(".revenue_yoy") || row.path.endsWith(".projection");
}

function buildEditableAxisGroups(editable: EditableAssumption[], representedPaths: Set<string>): AxisGroup[] {
  const grouped = new Map<EditableAssumption["group"], EditableAssumption[]>();
  for (const row of editable) {
    if (row.group === "terminal" || representedPaths.has(row.path)) continue;
    grouped.set(row.group, [...(grouped.get(row.group) ?? []), row]);
  }
  return [...grouped.entries()].map(([group, rows]) => ({
    title: EDITABLE_GROUP_LABELS[group] ?? group,
    rows: rows.map((row) => {
      const values: Record<string, number | null> = {};
      for (const cell of row.cells) values[cell.year] = cell.value;
      return {
        label: displayKnobLabel(row.label, row.path),
        values,
        note: [row.path, row.src, row.note].filter(Boolean).join("\n"),
        editablePath: row.path,
        format: editableAxisFormat(row),
      };
    }),
  }));
}

function buildAssumptionPatches(editable: EditableAssumption[], drafts: Record<string, number | null>): AssumptionPatch[] {
  const original = new Map<string, number | null>();
  for (const row of editable) {
    for (const cell of row.cells) original.set(cell.pointer, cell.value);
  }
  return Object.entries(drafts)
    .filter(([pointer, value]) => original.has(pointer) && original.get(pointer) !== value)
    .map(([pointer, value]) => ({
      pointer,
      old_value: original.get(pointer) ?? null,
      new_value: value,
    }));
}

function EditableAssumptionsTable({
  editable,
  editMode,
  drafts,
  onDraft,
}: {
  editable: EditableAssumption[];
  editMode: boolean;
  drafts: Record<string, number | null>;
  onDraft: (pointer: string, value: number | null) => void;
}) {
  const nonTerminal = editable.filter((row) => row.group !== "terminal");
  const terminal = editable.filter((row) => row.group === "terminal");
  const years = editableYears(nonTerminal);
  const grouped = new Map<EditableAssumption["group"], EditableAssumption[]>();
  for (const row of nonTerminal) grouped.set(row.group, [...(grouped.get(row.group) ?? []), row]);

  return (
    <div className="assumption-edit-stack">
      <div className="table-scroll workbook-scroll">
        <table className="financial-table unified-table assumption-edit-table">
          <thead>
            <tr className="year-header-row">
              <th>项目</th>
              {years.map((year) => (
                <th className="numeric forecast-year" key={year}>{year}E</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {[...grouped.entries()].map(([group, rows]) => (
              <Fragment key={group}>
                <tr className="group-header-row">
                  <th colSpan={years.length + 1}>{EDITABLE_GROUP_LABELS[group] ?? group}</th>
                </tr>
                {rows.map((row) => (
                  <tr key={row.id}>
                    <td className="statement-label" title={[row.path, row.src, row.note].filter(Boolean).join("\n")}>
                      <span>{row.label}</span>
                      <small>{row.path}</small>
                    </td>
                    {years.map((year) => {
                      const pointer = editablePointer(row, year);
                      const originalValue = editableOriginalValue(row, year);
                      const currentValue = pointer && pointer in drafts ? drafts[pointer] : originalValue;
                      const changed = pointer != null && pointer in drafts && drafts[pointer] !== originalValue;
                      return (
                        <td className={`numeric assumption-edit-cell ${changed ? "changed" : ""}`} key={`${row.id}-${year}`}>
                          {editMode && pointer ? (
                            <input
                              aria-label={`${row.label} ${year}`}
                              className="assumption-cell-input"
                              onChange={(event) => onDraft(pointer, parseEditableInput(row, event.currentTarget.value))}
                              type="number"
                              value={editableInputValue(row, currentValue)}
                            />
                          ) : (
                            editableDisplayValue(row, currentValue)
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
      {terminal.length ? (
        <div className="terminal-edit-strip">
          {terminal.map((row) => {
            const cell: EditableAssumptionCell | undefined = row.cells[0];
            const pointer = cell?.pointer;
            const originalValue = cell?.value ?? null;
            const currentValue = pointer && pointer in drafts ? drafts[pointer] : originalValue;
            const changed = pointer != null && pointer in drafts && drafts[pointer] !== originalValue;
            return (
              <label className={`terminal-edit-field ${changed ? "changed" : ""}`} key={row.id}>
                <span>{row.label}</span>
                {editMode && pointer ? (
                  <input
                    onChange={(event) => onDraft(pointer, parseEditableInput(row, event.currentTarget.value))}
                    type="number"
                    value={editableInputValue(row, currentValue)}
                  />
                ) : (
                  <strong>{editableDisplayValue(row, currentValue)}</strong>
                )}
              </label>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

function referenceFormat(block: StashBlock, display?: DisplayBlock): AxisRow["format"] {
  if (display?.metric === "gross_margin" || display?.metric === "rate" || display?.metric === "yoy") return display.metric === "yoy" ? "signedDecimal" : "decimal";
  if (display?.metric === "revenue" || display?.metric === "cost" || display?.metric === "amount") return "int";
  const text = `${block.name} ${block.unit ?? ""}`.toLowerCase();
  if (/pct|ratio|率|%/.test(text) && !/\/|mixed/.test(text)) return "decimal";
  if (/百万元|收入|成本|金额/.test(text)) return "int";
  return "num2";
}

function normalizeReferenceValues(values: Record<string, number | null>, format: AxisRow["format"], unit?: string | null): Record<string, number | null> {
  const normalized: Record<string, number | null> = {};
  for (const [key, value] of Object.entries(values)) {
    normalized[key] = normalizeAttachedValue(value, format, unit);
  }
  return normalized;
}

function referenceTitle(block: StashBlock, display?: DisplayBlock): string {
  const title = display?.title || block.name;
  if (display?.role === "deprecated" || display?.status === "deprecated") return `弃用/复盘 · ${title}`;
  if (display?.role === "check_only" || display?.status === "check_only") return `核对项 · ${title}`;
  if (display?.role === "technical") return `技术附注 · ${title}`;
  return title;
}

function buildReferenceGroups(refBlocks: StashBlock[], displayBlocks: Map<string, DisplayBlock> = new Map()): { groups: AxisGroup[]; rest: StashBlock[] } {
  const groups: AxisGroup[] = [];
  const rest: StashBlock[] = [];
  for (const b of refBlocks) {
    const display = displayForStash(b, displayBlocks);
    if (blockIsYearSeries(b)) {
      const format = referenceFormat(b, display);
      groups.push({
        title: referenceTitle(b, display),
        unit: b.unit,
        caveat: b.caveat,
        note: b.note,
        rows: b.items.filter(isSeriesItem).map((it) => ({ label: it.label, values: normalizeReferenceValues(it.values, format, b.unit), note: it.note, format })),
      });
    } else {
      rest.push(b);
    }
  }
  return { groups, rest };
}

const ANNUAL_DIMENSIONS = [
  { key: "product", label: "产品" },
  { key: "industry", label: "行业" },
  { key: "region", label: "地区" },
  { key: "sales_model", label: "销售模式" },
];

const ANNUAL_SOURCE_LABELS: Record<string, string> = {
  revenue_composition: "收入构成",
  major_business_profitability: "主营业务",
  business_profitability_yoy_split: "经营情况",
};

const ANNUAL_SERIES_ROWS = [
  { key: "revenue_yuan", label: "收入" },
  { key: "revenue_pct", label: "占比" },
  { key: "revenue_yoy_pct", label: "同比" },
  { key: "gross_margin_pct", label: "毛利率" },
] as const;

type AnnualSeriesMetric = (typeof ANNUAL_SERIES_ROWS)[number]["key"];

function normalizeDisclosureName(value: string): string {
  return value.replace(/[（）()及与和、/\\\s]/g, "").toLowerCase();
}

function disclosureShare(row: AnnualRevenueBreakdownRow, rows: AnnualRevenueBreakdownRow[]): number | null {
  if (typeof row.revenue_pct === "number" && !Number.isNaN(row.revenue_pct)) return row.revenue_pct;
  const total = rows.reduce((sum, item) => sum + (typeof item.revenue_yuan === "number" ? item.revenue_yuan : 0), 0);
  if (!total || typeof row.revenue_yuan !== "number") return null;
  return (row.revenue_yuan / total) * 100;
}

function annualMetricValue(
  row: AnnualRevenueBreakdownRow | undefined,
  metric: AnnualSeriesMetric,
  yearRows: AnnualRevenueBreakdownRow[],
): number | null {
  if (!row) return null;
  if (metric === "revenue_pct") return disclosureShare(row, yearRows);
  const value = row[metric];
  return typeof value === "number" && !Number.isNaN(value) ? value : null;
}

function formatAnnualMetric(value: number | null, metric: AnnualSeriesMetric): string {
  if (value == null) return "";
  if (metric === "revenue_yuan") return formatYuan(value);
  if (metric === "revenue_yoy_pct") return formatSignedPctPoint(value);
  return formatPctPoint(value);
}

function pickAnnualSeriesRow(
  candidates: AnnualRevenueBreakdownRow[],
  metric: AnnualSeriesMetric,
): AnnualRevenueBreakdownRow | undefined {
  if (!candidates.length) return undefined;
  const hasMetric = (row: AnnualRevenueBreakdownRow) => {
    if (metric === "revenue_pct") return typeof row.revenue_pct === "number" || typeof row.revenue_yuan === "number";
    return typeof row[metric] === "number";
  };
  const sourceScore = (row: AnnualRevenueBreakdownRow) => {
    if (metric === "revenue_pct") return row.source_table === "revenue_composition" ? 0 : 1;
    if (metric === "gross_margin_pct") return row.gross_margin_pct == null ? 2 : 0;
    return row.source_table === "major_business_profitability" ? 0 : 1;
  };
  return [...candidates].sort((left, right) => {
    const metricDelta = Number(!hasMetric(left)) - Number(!hasMetric(right));
    if (metricDelta !== 0) return metricDelta;
    const sourceDelta = sourceScore(left) - sourceScore(right);
    if (sourceDelta !== 0) return sourceDelta;
    return (right.revenue_yuan ?? 0) - (left.revenue_yuan ?? 0);
  })[0];
}

function AnnualRevenueDisclosure({
  rows,
  modelSegments,
}: {
  rows?: AnnualRevenueBreakdownRow[];
  modelSegments: Yaml1RevenueSegment[];
}) {
  const rawRows = rows ?? [];
  const availablePeriodTypes = useMemo(
    () =>
      [
        { key: "annual", label: "年度" },
        { key: "h1", label: "半年度" },
      ].filter((period) => rawRows.some((row) => (row.period_type ?? "annual") === period.key)),
    [rawRows],
  );
  const [periodType, setPeriodType] = useState<"annual" | "h1">("annual");
  useEffect(() => {
    if (availablePeriodTypes.length && !availablePeriodTypes.some((period) => period.key === periodType)) {
      setPeriodType(availablePeriodTypes[0].key as "annual" | "h1");
    }
  }, [availablePeriodTypes, periodType]);
  const allRows = useMemo(
    () => rawRows.filter((row) => (row.period_type ?? "annual") === periodType),
    [rawRows, periodType],
  );
  const years = useMemo(() => [...new Set(allRows.map((row) => row.year))].sort((a, b) => b - a), [allRows]);
  const seriesYears = useMemo(() => [...years].sort((a, b) => a - b), [years]);
  const structureYears = useMemo(() => years.slice(0, 3), [years]);
  const [viewMode, setViewMode] = useState<"structure" | "series">("series");
  const availableDimensions = useMemo(
    () => ANNUAL_DIMENSIONS.filter((dimension) => allRows.some((row) => row.dimension === dimension.key)),
    [allRows],
  );
  const activeDimensionDef = useMemo(
    () => availableDimensions.find((dimension) => dimension.key === "product") ?? availableDimensions[0] ?? { key: "product", label: "披露口径" },
    [availableDimensions],
  );
  const activeDimension = activeDimensionDef.key;
  const activeLabel = activeDimensionDef.label;
  const activePeriodLabel = availablePeriodTypes.find((period) => period.key === periodType)?.label ?? "年度";
  const formatPeriodHeader = (year: number) => (periodType === "h1" ? `${year}H1` : String(year));
  const latestYear = years[0] ?? null;
  const latestRows = useMemo(
    () =>
      allRows
        .filter((row) => row.year === latestYear && row.dimension === activeDimension)
        .sort((left, right) => (right.revenue_yuan ?? 0) - (left.revenue_yuan ?? 0)),
    [allRows, activeDimension, latestYear],
  );
  const dimensionRows = useMemo(() => allRows.filter((row) => row.dimension === activeDimension), [allRows, activeDimension]);
  const structureGroups = useMemo(
    () =>
      structureYears.map((year) => {
        const yearRows = dimensionRows
          .filter((row) => row.year === year)
          .sort((left, right) => (right.revenue_yuan ?? 0) - (left.revenue_yuan ?? 0));
        const total = yearRows.reduce((sum, row) => sum + (typeof row.revenue_yuan === "number" ? row.revenue_yuan : 0), 0);
        return { year, rows: yearRows, total };
      }),
    [dimensionRows, structureYears],
  );
  const seriesItems = useMemo(() => {
    const names = [...new Set(dimensionRows.map((row) => row.item_name).filter(Boolean))];
    return names
      .map((name) => {
        const latestRevenue = [...dimensionRows]
          .filter((row) => row.item_name === name && typeof row.revenue_yuan === "number")
          .sort((left, right) => right.year - left.year)[0]?.revenue_yuan ?? 0;
        return { name, latestRevenue };
      })
      .sort((left, right) => right.latestRevenue - left.latestRevenue || left.name.localeCompare(right.name, "zh-CN"));
  }, [dimensionRows]);

  const modelNames = useMemo(() => modelSegments.map((segment) => segment.name).filter(Boolean), [modelSegments]);
  const normalizedModelNames = useMemo(() => modelNames.map(normalizeDisclosureName), [modelNames]);
  const matchedRows = useMemo(() => {
    if (activeDimension !== "product" || !normalizedModelNames.length) return [];
    return latestRows.filter((row) => {
      const disclosed = normalizeDisclosureName(row.item_name);
      return normalizedModelNames.some((model) => disclosed.includes(model) || model.includes(disclosed));
    });
  }, [activeDimension, latestRows, normalizedModelNames]);
  const matchRate = latestRows.length ? matchedRows.length / latestRows.length : null;

  if (!rawRows.length) {
    return (
      <section className="card yaml-region annual-disclosure">
        <div className="yaml-region-heading">
          <div className="eyebrow">④ Annual report disclosure</div>
          <h2>年报披露口径</h2>
        </div>
        <div className="annual-empty">
          <h3>暂无年报披露拆分</h3>
          <p>当前公司还没有生成可展示的年报业务拆分数据。</p>
        </div>
      </section>
    );
  }

  return (
    <section className="card yaml-region annual-disclosure">
      <div className="yaml-region-heading annual-disclosure-heading">
        <div>
          <div className="eyebrow">④ Annual report disclosure</div>
          <h2>年报披露口径</h2>
        </div>
        <div className="annual-disclosure-stats">
          <div>
            <span>期间</span>
            <strong>{activePeriodLabel}</strong>
          </div>
          <div>
            <span>展示</span>
            <strong>{viewMode === "structure" ? "三年结构" : "时间序列"}</strong>
          </div>
          <div>
            <span>自动口径</span>
            <strong>{activeLabel}</strong>
          </div>
          <div>
            <span>模型匹配</span>
            <strong>{matchRate == null ? "-" : formatPercent(matchRate, 0)}</strong>
          </div>
        </div>
      </div>

      <div className="annual-disclosure-controls">
        {availablePeriodTypes.length > 1 ? (
          <div className="range-toggle annual-mode-toggle" role="group">
            {availablePeriodTypes.map((period) => (
              <button
                className={periodType === period.key ? "active" : ""}
                key={period.key}
                onClick={() => setPeriodType(period.key as "annual" | "h1")}
                type="button"
              >
                {period.label}
              </button>
            ))}
          </div>
        ) : null}
        <div className="range-toggle annual-mode-toggle" role="group">
          <button className={viewMode === "structure" ? "active" : ""} onClick={() => setViewMode("structure")} type="button">
            三年结构
          </button>
          <button className={viewMode === "series" ? "active" : ""} onClick={() => setViewMode("series")} type="button">
            时间序列
          </button>
        </div>
      </div>

      {viewMode === "series" && seriesItems.length ? (
        <div className="table-scroll workbook-scroll annual-series-table-wrap">
          <table className="financial-table annual-series-table">
            <thead>
              <tr>
                <th>{activeLabel}</th>
                {seriesYears.map((year) => (
                  <th className="numeric" key={year}>{formatPeriodHeader(year)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {seriesItems.map((item) => (
                <Fragment key={item.name}>
                  {ANNUAL_SERIES_ROWS.map((metric, metricIndex) => (
                    <tr className={metricIndex === 0 ? "annual-series-item-start" : "annual-series-metric-row"} key={`${item.name}-${metric.key}`}>
                      <td className={metricIndex === 0 ? "statement-label annual-series-item-label" : "statement-label annual-series-metric-label"}>
                        {metricIndex === 0 ? <span>{item.name}</span> : null}
                        <small>{metric.label}</small>
                      </td>
                      {seriesYears.map((year) => {
                        const rowsInYear = dimensionRows.filter((row) => row.year === year);
                        const row = pickAnnualSeriesRow(rowsInYear.filter((candidate) => candidate.item_name === item.name), metric.key);
                        const value = annualMetricValue(row, metric.key, rowsInYear);
                        return (
                          <td className={`numeric ${metric.key === "revenue_yoy_pct" && value != null && value < 0 ? "negative" : ""}`} key={year}>
                            {formatAnnualMetric(value, metric.key)}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {viewMode === "structure" && structureGroups.some((group) => group.rows.length > 0) ? (
        <div className="annual-structure-grid">
          {structureGroups.map((group) => (
            <article className="annual-structure-card" key={group.year}>
              <div className="annual-structure-card-head">
                <span>{formatPeriodHeader(group.year)}</span>
                <strong>{formatYuan(group.total)}</strong>
              </div>
              <div className="annual-structure-list">
                {group.rows.slice(0, 8).map((row) => {
                  const share = disclosureShare(row, group.rows);
                  return (
                    <div className="annual-structure-row" key={`${row.year}-${row.dimension}-${row.item_name}-${row.source_table}-${row.source_line}`}>
                      <div className="annual-structure-copy">
                        <span title={row.item_name}>{row.item_name}</span>
                        <small>{formatYuan(row.revenue_yuan)}{typeof row.revenue_yoy_pct === "number" ? ` · ${formatSignedPctPoint(row.revenue_yoy_pct)}` : ""}</small>
                      </div>
                      <div className="annual-structure-share">
                        <div className="annual-bar-track">
                          <span style={{ width: `${Math.max(2, Math.min(100, share ?? 0))}%` }} />
                        </div>
                        <strong>{share == null ? "-" : formatPctPoint(share, 1)}</strong>
                      </div>
                    </div>
                  );
                })}
              </div>
            </article>
          ))}
        </div>
      ) : null}

      {viewMode === "structure" && latestRows.length ? (
        <div className="table-scroll workbook-scroll annual-disclosure-table-wrap">
          <table className="financial-table annual-disclosure-table">
            <thead>
              <tr>
                <th>项目</th>
                <th className="numeric">收入</th>
                <th className="numeric">占比</th>
                <th className="numeric">同比</th>
                <th className="numeric">毛利率</th>
                <th>来源</th>
              </tr>
            </thead>
            <tbody>
              {latestRows.map((row) => {
                const share = disclosureShare(row, latestRows);
              return (
                  <tr key={`${row.year}-${row.dimension}-${row.item_name}-${row.source_table}-${row.source_line}`}>
                    <td className="statement-label">
                      <span>{row.item_name}</span>
                    </td>
                    <td className="numeric">{formatYuan(row.revenue_yuan)}</td>
                    <td className="numeric">{share == null ? "-" : formatPctPoint(share, 1)}</td>
                    <td className={`numeric ${typeof row.revenue_yoy_pct === "number" && row.revenue_yoy_pct < 0 ? "negative" : ""}`}>
                      {formatSignedPctPoint(row.revenue_yoy_pct)}
                    </td>
                    <td className="numeric">{formatPctPoint(row.gross_margin_pct)}</td>
                    <td>
                      <span className="source-chip">{ANNUAL_SOURCE_LABELS[row.source_table] ?? row.source_table}</span>
                    </td>
                  </tr>
              );
            })}
            </tbody>
          </table>
        </div>
      ) : null}

      {(viewMode === "structure" && !structureGroups.some((group) => group.rows.length > 0)) || (viewMode === "series" && !seriesItems.length) ? (
        <div className="annual-empty">
          <h3>当前维度无披露项</h3>
          <p>这一年报没有抽到该维度下的收入拆分。</p>
        </div>
      ) : null}
    </section>
  );
}

type YamlSubtab = "model" | "read" | "reference" | "disclosure";

function YamlWorkbook({
  companyId,
  initialPresentation,
  revenueView,
  statementSheets,
  fullStatementSheets,
  stashView,
  displayContract,
  assumptionsView,
  editableAssumptions,
  annualRevenueBreakdown,
  yaml1Text,
  path,
}: {
  companyId: string;
  initialPresentation?: Yaml1Presentation | null;
  revenueView?: Yaml1RevenueView | null;
  statementSheets?: StatementSheet[];
  fullStatementSheets?: StatementSheet[];
  stashView?: StashBlock[];
  displayContract?: Yaml1DisplayContract | null;
  assumptionsView?: Yaml1AssumptionsView | null;
  editableAssumptions?: EditableAssumption[];
  annualRevenueBreakdown?: AnnualRevenueBreakdownRow[];
  yaml1Text?: string | null;
  path?: string | null;
}) {
  const [presentation, setPresentation] = useState<Yaml1Presentation | null>(initialPresentation ?? null);
  const [presentationStatus, setPresentationStatus] = useState<string[]>([]);
  const [presentationError, setPresentationError] = useState<string | null>(null);
  const [presentationRunning, setPresentationRunning] = useState(false);
  const [editMode, setEditMode] = useState(false);
  const [draftValues, setDraftValues] = useState<Record<string, number | null>>({});
  const [preview, setPreview] = useState<AssumptionPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [briefPrompt, setBriefPrompt] = useState("");
  const [briefLoading, setBriefLoading] = useState(false);
  const [briefError, setBriefError] = useState<string | null>(null);
  const [inlineEdit, setInlineEdit] = useState<AssumptionInlineEdit | null>(null);
  const [yamlSubtab, setYamlSubtab] = useState<YamlSubtab>("model");
  const [modelRangeMode, setModelRangeMode] = useState<"recent" | "full">("recent");
  const editableRows = editableAssumptions ?? [];
  const patches = useMemo(() => buildAssumptionPatches(editableRows, draftValues), [editableRows, draftValues]);
  const editablePathMap = useMemo(() => editableRowsByPath(editableRows), [editableRows]);
  const editablePeriodList = useMemo(() => editablePeriods(editableRows), [editableRows]);
  const editablePeriodSet = useMemo(() => new Set(editablePeriodList), [editablePeriodList]);

  useEffect(() => {
    setPresentation(initialPresentation ?? null);
    setPresentationStatus([]);
    setPresentationError(null);
    setPresentationRunning(false);
    setEditMode(false);
    setDraftValues({});
    setPreview(null);
    setPreviewError(null);
    setBriefPrompt("");
    setBriefError(null);
    setInlineEdit(null);
    setYamlSubtab("model");
    setModelRangeMode("recent");
  }, [initialPresentation, path]);

  useEffect(() => {
    if (!editMode || patches.length === 0) {
      setPreview(null);
      setPreviewLoading(false);
      setPreviewError(null);
      return;
    }
    setPreviewLoading(true);
    const timer = window.setTimeout(() => {
      previewAssumptions(companyId, patches)
        .then((result) => {
          setPreview(result);
          const firstError = result.errors?.[0]?.message;
          setPreviewError(typeof firstError === "string" ? firstError : null);
        })
        .catch((error) => {
          setPreview(null);
          setPreviewError(error instanceof Error ? error.message : "Preview failed");
        })
        .finally(() => setPreviewLoading(false));
    }, 450);
    return () => window.clearTimeout(timer);
  }, [companyId, editMode, patches]);

  function generatePresentation() {
    setPresentationRunning(true);
    setPresentationError(null);
    setPresentationStatus(["已提交展示编排任务"]);
    const stream = new EventSource(`/api/companies/${encodeURIComponent(companyId)}/yaml1/presentation/stream?refresh=true`);
    stream.addEventListener("status", (event) => {
      const payload = JSON.parse((event as MessageEvent).data) as { message?: string; provider?: string | null; model?: string | null };
      const suffix = payload.provider || payload.model ? `（${[payload.provider, payload.model].filter(Boolean).join(" / ")}）` : "";
      setPresentationStatus((items) => [...items, `${payload.message ?? "处理中"}${suffix}`]);
    });
    stream.addEventListener("final", (event) => {
      const payload = JSON.parse((event as MessageEvent).data) as { presentation?: Yaml1Presentation };
      setPresentation(payload.presentation ?? null);
      setPresentationRunning(false);
      stream.close();
    });
    stream.onerror = () => {
      setPresentationError("展示编排连接中断，请检查后端服务和 .env 中的大模型配置。");
      setPresentationRunning(false);
      stream.close();
    };
  }

  function updateDraft(pointer: string, value: number | null) {
    setDraftValues((current) => ({ ...current, [pointer]: value }));
    setBriefPrompt("");
    setBriefError(null);
  }

  function startInlineEdit(assumption: EditableAssumption, cell: EditableAssumptionCell) {
    setInlineEdit({ pointer: cell.pointer, raw: editableInputValue(assumption, editableValueForCell(cell, draftValues)) });
  }

  function commitInlineEdit(assumption: EditableAssumption, cell: EditableAssumptionCell) {
    if (!inlineEdit || inlineEdit.pointer !== cell.pointer) return;
    updateDraft(cell.pointer, parseEditableInput(assumption, inlineEdit.raw));
    setInlineEdit(null);
  }

  async function generateBrief() {
    if (!patches.length) return;
    setBriefLoading(true);
    setBriefError(null);
    try {
      const result = await generateAssumptionBrief(companyId, patches);
      setBriefPrompt(result.prompt);
    } catch (error) {
      setBriefError(error instanceof Error ? error.message : "生成 prompt 失败");
    } finally {
      setBriefLoading(false);
    }
  }

  if (!revenueView && !assumptionsView && !editableRows.length && !stashView?.length && !annualRevenueBreakdown?.length) {
    return <EmptyState title="No YAML1" body="Compiler output yaml1_*.yaml was not found or could not be parsed." />;
  }

  const insightItems = presentation?.insights?.filter(Boolean) ?? [];
  const riskItems = presentation?.risks?.filter(Boolean) ?? [];
  const hasBusinessRead = insightItems.length > 0 || riskItems.length > 0;
  const leadInsight = insightItems[0] ?? "";
  const memoInsightItems = leadInsight ? insightItems.slice(1) : insightItems;

  // 三区一轴：每区一张表、一个共享年份轴，缺数据留空。约定分派，非公司特判。
  const allStash = stashView ?? [];
  const displayBlocks = displayBlockMap(displayContract);
  const displayWarnings = displayWarningsByPath(displayContract);
  const segmentAttachedBlocks = allStash.filter((b) => {
    const display = displayForStash(b, displayBlocks);
    if (display) return display.role === "primary_attachment" && display.placement === "model_table";
    return revenueView?.segments?.length ? attachableSegmentBlock(b, revenueView.segments) : false;
  });
  const segmentAttachedBlockSet = new Set(segmentAttachedBlocks);
  const secondaryBlocks = allStash.filter((b) => {
    if (segmentAttachedBlockSet.has(b)) return false;
    const display = displayForStash(b, displayBlocks);
    if (display) return display.role === "secondary_split" && display.placement === "secondary_table";
    return b.name.includes("拆分");
  });
  const secondaryBlockSet = new Set(secondaryBlocks);
  const refBlocks = allStash.filter((b) => !segmentAttachedBlockSet.has(b) && !secondaryBlockSet.has(b));

  // ① 收入拆分区
  const revenueBase = revenueView ? Number(revenueView.base_year) : 0;
  const revenueYears = revenueView
    ? unionYears([
        ...revenueView.segments.map((s) => Object.keys(s.history_revenues ?? {})),
        revenueView.years,
        ...secondaryBlocks.map(stashBlockYears),
        ...segmentAttachedBlocks.map(stashBlockYears),
        [String(revenueView.base_year)],
      ])
    : [];
  const revenueGroups = revenueView ? buildRevenueGroups(revenueView, presentation, secondaryBlocks, segmentAttachedBlocks, displayBlocks, displayWarnings, editableRows, fullStatementSheets, preview?.statement_sheets) : [];

  // ② 关键假设区
  const asmBase = assumptionsView ? Number(assumptionsView.base_period) : 0;
  const assumptionGroups = assumptionsView ? buildAssumptionsGroups(assumptionsView, fullStatementSheets) : [];
  const assumptionYears = assumptionsView?.years ?? [];
  const terminal = assumptionsView?.terminal;
  const representedEditablePaths = new Set<string>();
  for (const group of [...revenueGroups, ...assumptionGroups]) {
    for (const row of group.rows) {
      if (row.editablePath) representedEditablePaths.add(row.editablePath);
    }
  }
  const supplementalEditableRows = revenueView ? editableRows.filter((row) => row.group !== "revenue_driver") : editableRows;
  const supplementalEditableGroups = buildEditableAxisGroups(supplementalEditableRows, representedEditablePaths);
  const modelGroups = [...revenueGroups, ...supplementalEditableGroups, ...assumptionGroups];
  const modelYears = unionYears([revenueYears, assumptionYears, editablePeriodList]);
  const modelVisibleYears = useMemo(() => {
    if (modelRangeMode === "full") return modelYears;
    const base = revenueBase || asmBase;
    if (!base) return modelYears.slice(-5);
    const history = modelYears.filter((year) => Number(year) <= base).slice(-5);
    const forecast = modelYears.filter((year) => Number(year) > base);
    return [...history, ...forecast];
  }, [asmBase, modelRangeMode, modelYears, revenueBase]);

  // ③ 参考区
  const refBase = revenueBase || asmBase;
  const { groups: refGroups, rest: refRest } = buildReferenceGroups(refBlocks, displayBlocks);
  const refYears = unionYears(refGroups.map((g) => g.rows.flatMap((r) => Object.keys(r.values))));
  const displayWarningItems = displayContract?.warnings ?? [];

  return (
    <div className="view-stack yaml1-spec">
      {displayWarningItems.length ? (
        <div className="yaml-display-warnings">
          <strong>展示契约提示</strong>
          <span>{displayWarningItems.slice(0, 4).map((item) => item.message).join("；")}</span>
        </div>
      ) : null}

      <nav className="yaml-subtabs sheet-tabs compact-tabs" role="tablist" aria-label="核心假设展示子页面">
        {[
          ["model", "核心假设"],
          ["read", "业务解读"],
          ["reference", "参考项"],
          ["disclosure", "年报披露口径"],
        ].map(([key, label]) => (
          <button className={yamlSubtab === key ? "active" : ""} key={key} onClick={() => setYamlSubtab(key as YamlSubtab)} type="button">
            {label}
          </button>
        ))}
      </nav>

      {yamlSubtab === "model" ? (
      <section className="card yaml-region assumption-workbench-toolbar">
        <div className="yaml-region-heading">
          <div>
            <div className="eyebrow">Core assumption edit mode</div>
            <h2>核心假设工作台</h2>
            <p>更改核心假设请先点击「进入编辑」；可编辑的假设 cell 会自动高亮出现。这里的结果只是前端试算，编辑完必须回到 Claude Code 执行 /frontend-edit 更新假设并重算，才会写回正式模型。</p>
          </div>
          <div className="assumption-toolbar-actions">
            <button className={editMode ? "primary-button" : "secondary-button"} onClick={() => setEditMode((value) => !value)} type="button">
              {editMode ? "退出编辑" : "进入编辑"}
            </button>
            <button
              className="secondary-button"
              disabled={!patches.length}
              onClick={() => {
                setDraftValues({});
                setPreview(null);
                setPreviewError(null);
                setBriefPrompt("");
                setInlineEdit(null);
              }}
              type="button"
            >
              重置
            </button>
            <button className="primary-button" disabled={!patches.length || briefLoading} onClick={generateBrief} type="button">
              {briefLoading ? "生成中..." : "生成Claude Code指令"}
            </button>
          </div>
        </div>
        <div className="assumption-preview-status">
          <span>{patches.length ? `${patches.length} 处改动` : "无草稿改动"}</span>
          <span>{previewLoading ? "Preview 重算中..." : preview ? "Preview 已更新" : "使用正式 forecast"}</span>
          {preview?.dcf_summary?.per_share_value != null ? <strong>试算每股 {formatNumber(preview.dcf_summary.per_share_value, 2)}</strong> : null}
        </div>
        {patches.length ? (
          <div className="assumption-flow-alert">
            如果想保存本次假设编辑，请点击生成Claude Code指令按钮
          </div>
        ) : null}
        {previewError ? <div className="error-banner">{previewError}</div> : null}
        {briefError ? <div className="error-banner">{briefError}</div> : null}
        {briefPrompt ? (
          <div className="ka-prompt-box">
            <div className="eyebrow">frontend-edit 指令</div>
            <textarea readOnly value={briefPrompt} />
          </div>
        ) : null}
      </section>
      ) : null}

      {yamlSubtab === "model" && modelGroups.length > 0 ? (
        <section className="card yaml-region">
          <div className="yaml-region-heading model-table-heading">
            <div>
              <div className="eyebrow">① Model table</div>
              <h2>收入拆分 + 关键假设</h2>
            </div>
            <div className="range-toggle model-range-toggle" role="group">
              <button className={modelRangeMode === "recent" ? "active" : ""} onClick={() => setModelRangeMode("recent")} type="button">近5年 + 预测</button>
              <button className={modelRangeMode === "full" ? "active" : ""} onClick={() => setModelRangeMode("full")} type="button">展开全部年份</button>
            </div>
          </div>
          <UnifiedYearTable
            years={modelVisibleYears}
            baseYear={revenueBase || asmBase}
            groups={modelGroups}
            editMode={editMode}
            editableByPath={editablePathMap}
            editablePeriods={editablePeriodSet}
            drafts={draftValues}
            inlineEdit={inlineEdit}
            onCancelInlineEdit={() => setInlineEdit(null)}
            onCommitInlineEdit={commitInlineEdit}
            onInlineEditChange={(raw) => setInlineEdit((current) => current ? { ...current, raw } : current)}
            onStartInlineEdit={startInlineEdit}
          />
          {terminal && terminal.explicit_end != null ? <TerminalBlock terminal={terminal} /> : null}
        </section>
      ) : null}

      {yamlSubtab === "read" ? (
      <section className="card yaml-region business-read-panel">
        <div className="yaml-region-heading business-read-heading">
          <div>
            <div className="eyebrow">③ Business read</div>
            <h2>业务解读</h2>
          </div>
          <button className="primary-button" disabled={presentationRunning} onClick={generatePresentation} type="button">
            {presentationRunning ? "生成中..." : presentation ? "重新生成业务解读" : "生成业务解读"}
          </button>
        </div>

        {presentationStatus.length ? (
          <div className="ai-stream business-read-stream">
            {presentationStatus.map((item, index) => (
              <div className={index === presentationStatus.length - 1 && presentationRunning ? "active" : ""} key={`${item}-${index}`}>
                {item}
              </div>
            ))}
          </div>
        ) : null}

        {presentationError ? (
          <div className="error-banner business-read-error">{presentationError}</div>
        ) : null}

        {!presentationRunning && !presentationError && !hasBusinessRead ? (
          <div className="error-banner business-read-error">
            尚未生成业务解读，或当前 YAML1 presentation schema 不完整。请点击“生成业务解读”；若仍失败，请检查后端服务和 .env 中的大模型配置。
          </div>
        ) : null}

        {hasBusinessRead ? (
          <section className="business-read-memo">
            {leadInsight ? (
              <article className="business-read-lead">
                <div className="eyebrow">Primary read</div>
                <p>{leadInsight}</p>
              </article>
            ) : null}
            <div className="business-read-memo-grid">
              {memoInsightItems.length ? (
                <div className="business-read-memo-column">
                  <div className="memo-section-label">Drivers</div>
                  {memoInsightItems.map((item, index) => (
                    <article className="business-read-memo-item" key={item}>
                      <span>{String(index + 1).padStart(2, "0")}</span>
                      <p>{item}</p>
                    </article>
                  ))}
                </div>
              ) : null}
              {riskItems.length ? (
                <aside className="business-read-watchlist">
                  <div className="memo-section-label">Watchlist</div>
                  {riskItems.map((item, index) => (
                    <article className="business-read-risk-item" key={item}>
                      <span>{String(index + 1).padStart(2, "0")}</span>
                      <p>{item}</p>
                    </article>
                  ))}
                </aside>
              ) : null}
            </div>
          </section>
        ) : null}
      </section>
      ) : null}

      {yamlSubtab === "reference" && (refGroups.length > 0 || refRest.length > 0) ? (
        <section className="card yaml-region business-read-panel">
          <div className="yaml-region-heading">
            <div className="eyebrow">④ Reference items · stash</div>
            <h2>参考项</h2>
          </div>
          {refGroups.length > 0 ? (
            <UnifiedYearTable years={refYears} baseYear={refBase} groups={refGroups} />
          ) : null}
          {refRest.length > 0 ? (
            <div className="stash-blocks stash-rest">
          {refRest.map((b, i) => (
                <StashBlockView block={b} display={displayForStash(b, displayBlocks)} key={i} />
              ))}
            </div>
          ) : null}
        </section>
      ) : null}

      {yamlSubtab === "disclosure" ? <AnnualRevenueDisclosure rows={annualRevenueBreakdown} modelSegments={revenueView?.segments ?? []} /> : null}
    </div>
  );
}

type SensitivityState = {
  wacc: number;
  terminalGrowth: number;
  terminalCapexDaRatio: number;
};

function clampSensitivity(state: SensitivityState): SensitivityState {
  let wacc = Math.max(0.03, Math.min(0.25, state.wacc));
  let terminalGrowth = Math.max(-0.02, Math.min(0.1, state.terminalGrowth));
  let terminalCapexDaRatio = Math.max(0.5, Math.min(2.0, state.terminalCapexDaRatio));
  if (wacc <= terminalGrowth) {
    terminalGrowth = Math.max(-0.02, wacc - 0.005);
  }
  return { wacc, terminalGrowth, terminalCapexDaRatio };
}

function SensitivityCard({
  label,
  value,
  min,
  max,
  step,
  display,
  parse,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  display: (v: number) => string;
  parse: (raw: string) => number | null;
  onChange: (v: number) => void;
}) {
  const [text, setText] = useState(display(value));

  useEffect(() => {
    setText(display(value));
  }, [value, display]);

  const commit = () => {
    const parsed = parse(text);
    if (parsed === null) {
      setText(display(value));
      return;
    }
    const rounded = Math.round(parsed / step) * step;
    onChange(Math.max(min, Math.min(max, rounded)));
  };

  const stepUp = () => {
    onChange(Math.min(max, Math.round((value + step) / step) * step));
  };

  const stepDown = () => {
    onChange(Math.max(min, Math.round((value - step) / step) * step));
  };

  return (
    <div className="sensitivity-card-item">
      <span className="sensitivity-card-label">{label}</span>
      <input
        className="sensitivity-card-value"
        value={text}
        onChange={(event) => setText(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") commit();
        }}
      />
      <div className="sensitivity-card-buttons">
        <button className="sensitivity-card-button" onClick={stepDown} type="button">
          −
        </button>
        <button className="sensitivity-card-button" onClick={stepUp} type="button">
          +
        </button>
      </div>
    </div>
  );
}

function SensitivityPanel({
  initial,
  onChange,
  loading,
  error,
  compact = false,
}: {
  initial: SensitivityState;
  onChange: (state: SensitivityState) => void;
  loading: boolean;
  error?: string | null;
  compact?: boolean;
}) {
  const [values, setValues] = useState(initial);

  useEffect(() => {
    const timer = setTimeout(() => onChange(values), 700);
    return () => clearTimeout(timer);
  }, [values, onChange]);

  const update = (patch: Partial<SensitivityState>) => {
    setValues(clampSensitivity({ ...values, ...patch }));
  };

  return (
    <section className={`card sensitivity-card ${compact ? "compact" : ""}`}>
      <div className="section-heading">
        <div>
          <div className="eyebrow">DCF sensitivity</div>
          <h2>Terminal assumptions</h2>
        </div>
        {loading ? <span className="activity">Recalculating</span> : null}
      </div>
      {error ? <div className="error-banner sensitivity-error">{error}</div> : null}
      <div className="sensitivity-grid">
        <SensitivityCard
          label="WACC"
          value={values.wacc}
          min={0.03}
          max={0.25}
          step={0.005}
          display={(v) => formatPercent(v, 1)}
          parse={(raw) => {
            const cleaned = raw.replace(/%/g, "").trim();
            if (cleaned === "") return null;
            const num = Number(cleaned);
            return Number.isNaN(num) ? null : num / 100;
          }}
          onChange={(wacc) => update({ wacc })}
        />
        <SensitivityCard
          label="Terminal growth"
          value={values.terminalGrowth}
          min={-0.02}
          max={0.1}
          step={0.005}
          display={(v) => formatPercent(v, 1)}
          parse={(raw) => {
            const cleaned = raw.replace(/%/g, "").trim();
            if (cleaned === "") return null;
            const num = Number(cleaned);
            return Number.isNaN(num) ? null : num / 100;
          }}
          onChange={(terminalGrowth) => update({ terminalGrowth })}
        />
        <SensitivityCard
          label="Terminal CAPEX / D&A"
          value={values.terminalCapexDaRatio}
          min={0.5}
          max={2.0}
          step={0.05}
          display={(v) => `${v.toFixed(2)}x`}
          parse={(raw) => {
            const cleaned = raw.replace(/x/g, "").trim();
            if (cleaned === "") return null;
            const num = Number(cleaned);
            return Number.isNaN(num) ? null : num;
          }}
          onChange={(terminalCapexDaRatio) => update({ terminalCapexDaRatio })}
        />
      </div>
    </section>
  );
}

function StatementsView({ detail }: { detail: CompanyDetail }) {
  const sheets = detail.full_statement_sheets?.length ? detail.full_statement_sheets : detail.statement_sheets ?? [];
  const [active, setActive] = useState(sheets[0]?.key ?? "is");
  const [showZeroRows, setShowZeroRows] = useState(false);
  const [showTechnicalRows, setShowTechnicalRows] = useState(false);
  const [rangeMode, setRangeMode] = useState<"full" | "recent">("recent");
  const activeSheet = sheets.find((sheet) => sheet.key === active);
  const basePeriod = String(detail.dcf_summary?.base_period ?? detail.summary.base_period ?? "");
  // 显式预测期上限：yaml1 terminal.explicit_end。近5年模式下只展示到该年，丢掉 fade 期。
  const explicitEnd = detail.yaml1_assumptions_view?.terminal?.explicit_end ?? null;

  const visibleYears = useMemo(() => {
    if (!activeSheet) return [] as string[];
    const base = Number(basePeriod);
    const all = activeSheet.years;
    if (rangeMode === "full") return all;
    const hist = all.filter((y) => (Number(y) || 0) <= base).slice(-5);
    let fcst = all.filter((y) => (Number(y) || 0) > base);
    if (explicitEnd != null) {
      fcst = fcst.filter((y) => (Number(y) || 0) <= Number(explicitEnd));
    }
    return [...hist, ...fcst];
  }, [activeSheet, basePeriod, rangeMode, explicitEnd]);

  if (!sheets.length) {
    return <EmptyState title="No forecast tables" body="Run the DCF model to generate forecast/ outputs." />;
  }

  return (
    <div className="view-stack">
      <div className="workbook-shell">
        <div className="workbook-header">
          <div>
            <div className="eyebrow">完整三表 · 历史 + 预测</div>
            <h2>Income Statement / Balance Sheet / Cash Flow</h2>
          </div>
          <div className="workbook-toggles">
            <div className="range-toggle" role="group">
              <button className={rangeMode === "recent" ? "active" : ""} onClick={() => setRangeMode("recent")} type="button">近5年 + 预测</button>
              <button className={rangeMode === "full" ? "active" : ""} onClick={() => setRangeMode("full")} type="button">完整历史</button>
            </div>
            <label className="zero-toggle">
              <input checked={showZeroRows} onChange={(event) => setShowZeroRows(event.currentTarget.checked)} type="checkbox" />
              显示零值行
            </label>
            <label className="zero-toggle">
              <input checked={showTechnicalRows} onChange={(event) => setShowTechnicalRows(event.currentTarget.checked)} type="checkbox" />
              显示技术口径
            </label>
          </div>
        </div>
        <SheetTabs active={active} items={sheets.map((sheet) => ({ key: sheet.key, label: sheet.name, count: sheet.rows.length }))} onSelect={setActive} />
        {activeSheet ? (
          <FullStatementTable basePeriod={basePeriod} derivedMetrics={detail.derived_metrics} sheet={activeSheet} showTechnicalRows={showTechnicalRows} showZeroRows={showZeroRows} years={visibleYears} />
        ) : null}
      </div>
    </div>
  );
}

function dcfSensitivityStorageKey(companyId: string): string {
  return `mka.dcf_sensitivity_${companyId}`;
}

function loadSavedSensitivity(companyId: string): SensitivityState | null {
  try {
    const raw = window.localStorage.getItem(dcfSensitivityStorageKey(companyId));
    if (raw) return clampSensitivity(JSON.parse(raw) as SensitivityState);
  } catch {
    // ignore corrupt storage
  }
  return null;
}

function DcfView({ detail }: { detail: CompanyDetail }) {
  const [dcf, setDcf] = useState(detail.dcf_summary);
  const [sensitivityLoading, setSensitivityLoading] = useState(false);
  const [sensitivityError, setSensitivityError] = useState<string | null>(null);

  useEffect(() => {
    setDcf(detail.dcf_summary);
  }, [detail.dcf_summary]);

  const initialSensitivity = useMemo<SensitivityState>(() => {
    const saved = loadSavedSensitivity(detail.summary.id);
    return saved ?? {
      wacc: Number(detail.dcf_summary?.wacc ?? 0.08),
      terminalGrowth: Number(detail.dcf_summary?.terminal_growth ?? 0.025),
      terminalCapexDaRatio: Number(detail.dcf_summary?.terminal_capex_da_ratio ?? 1.0),
    };
  }, [detail.summary.id, detail.dcf_summary?.wacc, detail.dcf_summary?.terminal_growth, detail.dcf_summary?.terminal_capex_da_ratio]);

  async function handleSensitivityChange(state: SensitivityState) {
    if (detail.summary.id) {
      window.localStorage.setItem(dcfSensitivityStorageKey(detail.summary.id), JSON.stringify(state));
    }
    if (!detail.summary.id) return;
    setSensitivityLoading(true);
    setSensitivityError(null);
    try {
      const result = await apiPostJson<{ summary: Record<string, unknown> }>(
        `/api/companies/${encodeURIComponent(detail.summary.id)}/dcf-sensitivity`,
        {
          wacc: state.wacc,
          terminal_growth: state.terminalGrowth,
          terminal_capex_da_ratio: state.terminalCapexDaRatio,
        },
      );
      setDcf(result.summary);
    } catch (err) {
      setSensitivityError(err instanceof Error ? err.message : "Sensitivity failed");
    } finally {
      setSensitivityLoading(false);
    }
  }

  const marketCap = detail.summary.market_cap ?? detail.derived_metrics?.market_snapshot?.total_mv;
  const equityValue = dcf?.equity_value;
  const upside = (typeof equityValue === "number" && typeof marketCap === "number" && marketCap !== 0)
    ? equityValue / marketCap - 1
    : null;

  const ratingConfig = detail.rating_report ?? DEFAULT_RATING_REPORT_CONFIG;
  const years = overviewRange(detail.rating_report);
  const forecastYears = years.filter((year) => year.forecast);
  const forecastFirstYear = forecastYears[0]?.year ?? ratingConfig.forecast_start_year;
  const forecastSecondYear = forecastYears[1]?.year ?? forecastFirstYear + 1;
  const firstForecastPe = overviewMetric(detail, "pe", forecastFirstYear) ?? asNumber(detail.derived_metrics?.valuation?.forward_pe);
  const secondForecastPe = overviewMetric(detail, "pe", forecastSecondYear);
  const dcfEquityValue = asNumber(dcf?.equity_value);
  const perShareValue = asNumber(dcf?.per_share_value ?? detail.derived_metrics?.valuation?.per_share_value ?? detail.summary.per_share_value);
  const dcfTargetPe = (year: number): number | null => {
    const eps = overviewMetric(detail, "eps", year);
    if (perShareValue != null && eps != null && eps !== 0) return perShareValue / eps;
    const attrNetIncome = overviewMetric(detail, "n_income_attr_p", year);
    if (dcfEquityValue != null && attrNetIncome != null && attrNetIncome !== 0) {
      return dcfEquityValue / attrNetIncome;
    }
    return null;
  };
  const firstDcfTargetPe = dcfTargetPe(forecastFirstYear);
  const secondDcfTargetPe = dcfTargetPe(forecastSecondYear);

  return (
    <div className="view-stack">
      <section className="metric-grid dcf-pe-grid">
        <MetricCard label={`${forecastYearLabel(forecastFirstYear)} PE`} value={formatMultiple(firstForecastPe, 1)} caption="未来估值" />
        <MetricCard label={`${forecastYearLabel(forecastSecondYear)} PE`} value={formatMultiple(secondForecastPe, 1)} caption="未来估值" />
        <MetricCard label={`${forecastYearLabel(forecastFirstYear)} DCF目标价对应PE`} value={formatMultiple(firstDcfTargetPe, 1)} caption="DCF视角下的PE" />
        <MetricCard label={`${forecastYearLabel(forecastSecondYear)} DCF目标价对应PE`} value={formatMultiple(secondDcfTargetPe, 1)} caption="DCF视角下的PE" />
      </section>
      <div className="dcf-topline">
        <section className="metric-grid dcf-metric-grid">
          <MetricCard label="Equity value" value={formatYiFromMillion(dcf?.equity_value)} caption="亿元" tone="highlight" />
          <MetricCard label="目前市值" value={formatYiFromMillion(detail.summary.market_cap ?? detail.derived_metrics?.market_snapshot?.total_mv)} caption="亿元" tone="highlight" />
          <MetricCard label="Per-share value" value={formatNumber(dcf?.per_share_value)} caption="元/股" />
          <MetricCard label="模型相对市值空间" value={formatPercent(upside, 1)} caption={upside != null ? (upside >= 0 ? "模型溢价" : "模型折价") : "-"} />
        </section>
        <SensitivityPanel
          key={detail.summary.id}
          compact
          error={sensitivityError}
          initial={initialSensitivity}
          loading={sensitivityLoading}
          onChange={handleSensitivityChange}
        />
      </div>
      <ValuationBridge dcf={dcf} detail={detail.dcf_detail ?? []} />
    </div>
  );
}

const REVERSE_CHART = {
  width: 760,
  height: 480,
  left: 68,
  right: 26,
  top: 26,
  bottom: 58,
};

function formatRatio(value: number | null | undefined, digits = 2): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "-";
  return value.toFixed(digits);
}

function reverseTicks(domain: [number, number]): number[] {
  const step = 0.1;
  const ticks: number[] = [];
  const start = Math.ceil(domain[0] / step) * step;
  for (let value = start; value <= domain[1] + 1e-9; value += step) {
    ticks.push(Math.round(value * 1000) / 1000);
  }
  return ticks;
}

function lineSegmentForDecay(k: number, domain: [number, number]): Array<{ g1: number; g2: number }> {
  const candidates = [
    { g1: domain[0], g2: k * domain[0] },
    { g1: domain[1], g2: k * domain[1] },
  ];
  if (Math.abs(k) > 1e-9) {
    candidates.push({ g1: domain[0] / k, g2: domain[0] });
    candidates.push({ g1: domain[1] / k, g2: domain[1] });
  } else if (domain[0] <= 0 && domain[1] >= 0) {
    candidates.push({ g1: domain[0], g2: 0 });
    candidates.push({ g1: domain[1], g2: 0 });
  }
  const unique = candidates
    .filter((point) => pointInDomain(point, domain))
    .filter((point, index, list) => list.findIndex((item) => Math.abs(item.g1 - point.g1) < 1e-8 && Math.abs(item.g2 - point.g2) < 1e-8) === index)
    .sort((a, b) => a.g1 - b.g1);
  if (unique.length < 2) return [];
  return [unique[0], unique[unique.length - 1]];
}

function ReverseSlider({
  label,
  value,
  min,
  max,
  step,
  format,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  format: (value: number) => string;
  onChange: (value: number) => void;
}) {
  return (
    <label className="reverse-slider">
      <span className="reverse-slider-header">
        <span>{label}</span>
        <strong>{format(value)}</strong>
      </span>
      <input
        max={max}
        min={min}
        onChange={(event) => onChange(Number(event.currentTarget.value))}
        step={step}
        type="range"
        value={value}
      />
    </label>
  );
}

function ReverseDcfChart({
  base,
  inputs,
  curve,
  selected,
  referencePoint,
  modelPoint,
  onSelect,
}: {
  base: ReverseDcfBase;
  inputs: ReverseDcfInputs;
  curve: ReverseDcfPoint[];
  selected: ReverseDcfPoint | null;
  referencePoint: ReverseDcfPoint | null;
  modelPoint: { g1: number; g2: number } | null;
  onSelect: (point: ReverseDcfPoint) => void;
}) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [dragging, setDragging] = useState(false);
  const domain = base.bounds.growth;
  const plotW = REVERSE_CHART.width - REVERSE_CHART.left - REVERSE_CHART.right;
  const plotH = REVERSE_CHART.height - REVERSE_CHART.top - REVERSE_CHART.bottom;
  const ticks = reverseTicks(domain);
  const toX = (g1: number) => REVERSE_CHART.left + ((g1 - domain[0]) / (domain[1] - domain[0])) * plotW;
  const toY = (g2: number) => REVERSE_CHART.top + ((domain[1] - g2) / (domain[1] - domain[0])) * plotH;
  const curvePath = curve.map((point, index) => `${index === 0 ? "M" : "L"} ${toX(point.g1).toFixed(2)} ${toY(point.g2).toFixed(2)}`).join(" ");
  const decayLine = lineSegmentForDecay(inputs.referenceDecay, domain);

  const clientToGrowth = (event: ReactPointerEvent<SVGSVGElement>) => {
    const svg = svgRef.current;
    if (!svg) return null;
    const rect = svg.getBoundingClientRect();
    const viewX = ((event.clientX - rect.left) / rect.width) * REVERSE_CHART.width;
    const viewY = ((event.clientY - rect.top) / rect.height) * REVERSE_CHART.height;
    const clampedX = clampValue(viewX, REVERSE_CHART.left, REVERSE_CHART.left + plotW);
    const clampedY = clampValue(viewY, REVERSE_CHART.top, REVERSE_CHART.top + plotH);
    return {
      g1: domain[0] + ((clampedX - REVERSE_CHART.left) / plotW) * (domain[1] - domain[0]),
      g2: domain[1] - ((clampedY - REVERSE_CHART.top) / plotH) * (domain[1] - domain[0]),
    };
  };

  const selectNearest = (event: ReactPointerEvent<SVGSVGElement>) => {
    const growth = clientToGrowth(event);
    if (!growth) return;
    const nearest = nearestCurvePoint(curve, growth.g1, growth.g2);
    if (nearest) onSelect(nearest);
  };

  return (
    <section className="reverse-chart-panel">
      <svg
        aria-label="逆向 DCF 等股权价值曲线"
        className="reverse-chart"
        onPointerDown={(event) => {
          setDragging(true);
          try {
            event.currentTarget.setPointerCapture(event.pointerId);
          } catch {
            // Synthetic pointer events used in automation may not have an active pointer.
          }
          selectNearest(event);
        }}
        onPointerMove={(event) => {
          if (dragging) selectNearest(event);
        }}
        onPointerUp={(event) => {
          setDragging(false);
          if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
            event.currentTarget.releasePointerCapture(event.pointerId);
          }
        }}
        onPointerCancel={() => setDragging(false)}
        ref={svgRef}
        role="img"
        viewBox={`0 0 ${REVERSE_CHART.width} ${REVERSE_CHART.height}`}
      >
        <rect className="reverse-plot-bg" height={plotH} width={plotW} x={REVERSE_CHART.left} y={REVERSE_CHART.top} />
        {ticks.map((tick) => (
          <Fragment key={`x-${tick}`}>
            <line className="reverse-grid" x1={toX(tick)} x2={toX(tick)} y1={REVERSE_CHART.top} y2={REVERSE_CHART.top + plotH} />
            <text className="reverse-axis-label" textAnchor="middle" x={toX(tick)} y={REVERSE_CHART.top + plotH + 28}>{formatPercent(tick, 0)}</text>
          </Fragment>
        ))}
        {ticks.map((tick) => (
          <Fragment key={`y-${tick}`}>
            <line className="reverse-grid" x1={REVERSE_CHART.left} x2={REVERSE_CHART.left + plotW} y1={toY(tick)} y2={toY(tick)} />
            <text className="reverse-axis-label" textAnchor="end" x={REVERSE_CHART.left - 12} y={toY(tick) + 4}>{formatPercent(tick, 0)}</text>
          </Fragment>
        ))}
        <line className="reverse-axis" x1={REVERSE_CHART.left} x2={REVERSE_CHART.left + plotW} y1={toY(0)} y2={toY(0)} />
        <line className="reverse-axis" x1={toX(0)} x2={toX(0)} y1={REVERSE_CHART.top} y2={REVERSE_CHART.top + plotH} />
        {decayLine.length === 2 ? (
          <line
            className="reverse-decay-line"
            x1={toX(decayLine[0].g1)}
            x2={toX(decayLine[1].g1)}
            y1={toY(decayLine[0].g2)}
            y2={toY(decayLine[1].g2)}
          />
        ) : null}
        {curvePath ? <path className="reverse-curve" d={curvePath} /> : null}
        {modelPoint && pointInDomain(modelPoint, domain) ? (
          <g className="reverse-model-point" transform={`translate(${toX(modelPoint.g1)} ${toY(modelPoint.g2)})`}>
            <rect height="10" rx="2" width="10" x="-5" y="-5" />
          </g>
        ) : null}
        {referencePoint ? (
          <circle className="reverse-reference-point" cx={toX(referencePoint.g1)} cy={toY(referencePoint.g2)} r="5" />
        ) : null}
        {selected ? (
          <g className="reverse-selected-point" transform={`translate(${toX(selected.g1)} ${toY(selected.g2)})`}>
            <circle r="9" />
            <circle r="15" />
          </g>
        ) : null}
        <text className="reverse-axis-title" textAnchor="middle" x={REVERSE_CHART.left + plotW / 2} y={REVERSE_CHART.height - 12}>g1 显式期利润 CAGR（NOPAT）</text>
        <text className="reverse-axis-title" textAnchor="middle" transform={`translate(18 ${REVERSE_CHART.top + plotH / 2}) rotate(-90)`}>g2 中期利润 CAGR（NOPAT）</text>
      </svg>
      {!curve.length ? <div className="reverse-chart-empty">当前参数范围内没有可见的等市值解。</div> : null}
    </section>
  );
}

function ReverseDcfReadout({
  base,
  point,
  modelCagr,
}: {
  base: ReverseDcfBase;
  point: ReverseDcfPoint | null;
  modelCagr: ModelSegmentCagr;
}) {
  const modelVsMarketG1 = point && modelCagr.g1 != null ? modelCagr.g1 - point.g1 : null;
  const modelVsMarketG2 = point && modelCagr.g2 != null ? modelCagr.g2 - point.g2 : null;
  return (
    <section className="reverse-readout">
      <div className="reverse-gap-box">
        <div className="reverse-gap-head">
          <div>
            <div className="eyebrow">核心读数</div>
            <h2>市场隐含利润增速 vs 目前模型利润假设</h2>
          </div>
          <span>NOPAT CAGR</span>
        </div>
        <div className="reverse-gap-grid">
          <div className="reverse-gap-column implied">
            <span>市场隐含</span>
            <strong>{formatPercent(point?.g1, 1)}</strong>
            <small>g1 显式期利润</small>
            <strong>{formatPercent(point?.g2, 1)}</strong>
            <small>g2 中期利润</small>
          </div>
          <div className="reverse-gap-column model">
            <span>目前模型</span>
            <strong>{formatPercent(modelCagr.g1, 1)}</strong>
            <small>g1 显式期利润</small>
            <strong>{formatPercent(modelCagr.g2, 1)}</strong>
            <small>g2 中期利润</small>
          </div>
          <div className="reverse-gap-column delta">
            <span>模型相对市场</span>
            <strong>{formatSignedPercent(modelVsMarketG1, 1)}</strong>
            <small>g1：模型 - 市场</small>
            <strong>{formatSignedPercent(modelVsMarketG2, 1)}</strong>
            <small>g2：模型 - 市场</small>
          </div>
        </div>
        <div className="reverse-gap-note">正值表示目前模型比市场隐含更激进；负值表示目前模型低于市场隐含。</div>
      </div>
      <div className="reverse-secondary-grid">
        <div className="reverse-readout-row">
          <span>隐含衰减 k（g2/g1）</span>
          <strong>{formatRatio(point?.k, 2)}</strong>
        </div>
        <div className="reverse-readout-row">
          <span>终值 PV / 当前市值</span>
          <strong>{formatPercent(point?.terminalShareOfMarket, 1)}</strong>
        </div>
        <div className="reverse-readout-row">
          <span>目标股权价值</span>
          <strong>{formatYiFromMillion(base.market.market_cap)} 亿元</strong>
        </div>
      </div>
      {point && point.terminalShareOfMarket > 0.7 ? (
        <div className="reverse-warning">终值 PV 占当前市值比例偏高；WACC 与远期增长率会显著扭曲这条曲线。</div>
      ) : null}
    </section>
  );
}

function ReverseDcfTool({ base }: { base: ReverseDcfBase }) {
  const [inputs, setInputs] = useState<ReverseDcfInputs>(() => defaultReverseDcfInputs(base));
  const [manualPoint, setManualPoint] = useState<{ g1: number; g2: number } | null>(null);
  const [referenceDecayMode, setReferenceDecayMode] = useState<"auto" | "manual">("auto");

  useEffect(() => {
    setInputs(defaultReverseDcfInputs(base));
    setManualPoint(null);
    setReferenceDecayMode("auto");
  }, [base]);

  const updateInputs = (patch: Partial<ReverseDcfInputs>) => {
    setInputs((current) => {
      const next = { ...current, ...patch };
      return {
        n1: Math.round(clampValue(next.n1, base.bounds.n1[0], base.bounds.n1[1])),
        n2: Math.round(clampValue(next.n2, base.bounds.n2[0], base.bounds.n2[1])),
        wacc: clampValue(next.wacc, base.bounds.wacc[0], base.bounds.wacc[1]),
        terminalGrowth: clampValue(next.terminalGrowth, base.bounds.terminal_growth[0], Math.min(base.bounds.terminal_growth[1], next.wacc - 0.001)),
        referenceDecay: clampValue(next.referenceDecay, base.bounds.reference_decay[0], base.bounds.reference_decay[1]),
      };
    });
  };

  const updateReferenceDecay = (referenceDecay: number) => {
    setReferenceDecayMode("manual");
    setManualPoint(null);
    updateInputs({ referenceDecay });
  };

  const curve = useMemo(() => generateIsoCurve(base, inputs), [base, inputs]);
  const modelCagr = useMemo(() => modelSegmentCagr(base, inputs.n1, inputs.n2), [base, inputs.n1, inputs.n2]);
  const modelPoint = modelCagr.g1 != null && modelCagr.g2 != null ? { g1: modelCagr.g1, g2: modelCagr.g2 } : null;
  const g1ParityWacc = useMemo(() => solveWaccForModelG1Parity(base, inputs), [base, inputs.n1, inputs.n2, inputs.terminalGrowth, inputs.referenceDecay]);
  const waccAnchorHint = g1ParityWacc == null
    ? "当前参数无法在 WACC 边界内让 g1：模型 - 市场 = 0，已使用默认折现率。"
    : Math.abs(inputs.wacc - g1ParityWacc) < 0.0005
      ? `默认 WACC 已校准到 g1：模型 - 市场 = 0（${formatPercent(g1ParityWacc, 1)}）。`
      : `当前分段的 g1 对齐 WACC 参考值：${formatPercent(g1ParityWacc, 1)}。`;
  const autoReferencePoint = useMemo(
    () => referencePointForTargetG2(base, inputs, modelCagr.g2),
    [base, inputs, modelCagr.g2],
  );
  const usableAutoReferencePoint = autoReferencePoint?.k != null && Number.isFinite(autoReferencePoint.k) ? autoReferencePoint : null;
  const autoReferenceDecay = usableAutoReferencePoint?.k ?? base.defaults.reference_decay;
  const referenceDecay = referenceDecayMode === "manual" ? inputs.referenceDecay : autoReferenceDecay;
  const effectiveInputs = useMemo(() => ({ ...inputs, referenceDecay }), [inputs, referenceDecay]);
  const referencePoint = useMemo(
    () => (
      referenceDecayMode === "manual"
        ? referenceIntersection(base, effectiveInputs, curve)
        : usableAutoReferencePoint ?? referenceIntersection(base, effectiveInputs, curve)
    ),
    [base, curve, effectiveInputs, referenceDecayMode, usableAutoReferencePoint],
  );
  const selectedPoint = useMemo(() => {
    if (!curve.length) return null;
    if (manualPoint) return nearestCurvePoint(curve, manualPoint.g1, manualPoint.g2) ?? referencePoint;
    return referencePoint ?? curve[Math.floor(curve.length / 2)] ?? null;
  }, [curve, manualPoint, referencePoint]);
  const referenceDecayMin = Math.min(base.bounds.reference_decay[0], referenceDecay);
  const referenceDecayMax = Math.max(base.bounds.reference_decay[1], referenceDecay);
  const isAutoAnchored = referenceDecayMode === "auto" && Boolean(usableAutoReferencePoint);
  const referenceHint = referenceDecayMode === "manual"
    ? "当前为手动衰减；市场隐含点来自这条 k 线与等股权价值曲线的交点。"
    : isAutoAnchored
      ? `自动锚定：市场隐含 g2 = 目前模型 g2（${formatPercent(modelCagr.g2, 1)}）。`
      : "未能在当前图域内匹配模型 g2，已回退到默认参考衰减。";
  const resetReferenceAnchor = () => {
    setManualPoint(null);
    setReferenceDecayMode("auto");
  };

  return (
    <div className="reverse-shell">
      <section className="reverse-parameter-bar">
        <div className="reverse-parameter-group">
          <div className="eyebrow">分段结构</div>
          <ReverseSlider label="N1 显式期年数" value={inputs.n1} min={base.bounds.n1[0]} max={base.bounds.n1[1]} step={1} format={(value) => `${Math.round(value)}年`} onChange={(n1) => updateInputs({ n1 })} />
          <ReverseSlider label="N2 中期年数" value={inputs.n2} min={base.bounds.n2[0]} max={base.bounds.n2[1]} step={1} format={(value) => `${Math.round(value)}年`} onChange={(n2) => updateInputs({ n2 })} />
        </div>
        <div className="reverse-parameter-group">
          <div className="eyebrow">钉死假设</div>
          <ReverseSlider label="WACC" value={inputs.wacc} min={base.bounds.wacc[0]} max={base.bounds.wacc[1]} step={0.0025} format={(value) => formatPercent(value, 1)} onChange={(wacc) => updateInputs({ wacc })} />
          <ReverseSlider label="远期增长 g∞" value={inputs.terminalGrowth} min={base.bounds.terminal_growth[0]} max={Math.min(base.bounds.terminal_growth[1], inputs.wacc - 0.001)} step={0.0025} format={(value) => formatPercent(value, 1)} onChange={(terminalGrowth) => updateInputs({ terminalGrowth })} />
          <div className="reverse-anchor-note">{waccAnchorHint}</div>
        </div>
      </section>

      <section className="reverse-context-strip">
        <div><span>当前市值</span><strong>{formatYiFromMillion(base.market.market_cap)} 亿元</strong></div>
        <div><span>目标股权价值</span><strong>{formatYiFromMillion(base.market.market_cap)} 亿元</strong></div>
        <div><span>当前股价</span><strong>{base.market.close != null ? formatNumber(base.market.close, 2) : "-"}</strong></div>
        <div><span>目前模型利润假设</span><strong>{modelPoint ? `${formatPercent(modelPoint.g1, 1)} / ${formatPercent(modelPoint.g2, 1)}` : "-"}</strong></div>
      </section>

      {base.warnings.length ? <div className="reverse-warning">{base.warnings.join(" ")}</div> : null}

      <div className="reverse-workbench">
        <ReverseDcfReadout base={base} point={selectedPoint} modelCagr={modelCagr} />
        <div className="reverse-chart-stack">
          <div className="reverse-chart-toolbar">
            <div>
              <div className="eyebrow">等股权价值曲线</div>
              <h2>当前市值约束</h2>
            </div>
            <div className="reverse-decay-control">
              <div className="reverse-decay-slider-block">
                <ReverseSlider label="参考衰减 k = g2/g1" value={referenceDecay} min={referenceDecayMin} max={referenceDecayMax} step={0.01} format={(value) => value.toFixed(2)} onChange={updateReferenceDecay} />
                <p>{referenceHint}</p>
              </div>
              <button className="reverse-anchor-button" disabled={!manualPoint && referenceDecayMode === "auto"} onClick={resetReferenceAnchor} type="button">
                {referenceDecayMode === "manual" ? "回到模型 g2 锚点" : "回到参考交点"}
              </button>
            </div>
          </div>
          <ReverseDcfChart
            base={base}
            curve={curve}
            inputs={effectiveInputs}
            onSelect={(point) => setManualPoint({ g1: point.g1, g2: point.g2 })}
            referencePoint={referencePoint}
            selected={selectedPoint}
            modelPoint={modelPoint}
          />
        </div>
      </div>
    </div>
  );
}

function reverseBaseIsProfitPack(base: ReverseDcfBase): boolean {
  return (
    base.base_model.growth_metric === "nopat"
    && Number.isFinite(base.base_model.base_nopat)
    && Array.isArray(base.base_model.current_model_profit_yoy)
    && base.yearly.every((year) => Number.isFinite(year.fcff_to_nopat) && Number.isFinite(year.terminal_fcff_to_nopat))
  );
}

function ReverseDcfView({ detail }: { detail: CompanyDetail }) {
  const [base, setBase] = useState<ReverseDcfBase | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setBase(null);
    apiGet<ReverseDcfBase>(`/api/companies/${encodeURIComponent(detail.summary.id)}/reverse-dcf-base`)
      .then((result) => {
        if (!cancelled) setBase(result);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [detail.summary.id]);

  if (loading) return <div className="activity content-activity">正在加载逆向 DCF 参数包</div>;
  if (error) return <div className="error-banner">{error}</div>;
  if (!base) return <EmptyState title="逆向 DCF 暂不可用" body="请先运行正式 DCF，再重新打开这个页面。" />;
  if (!reverseBaseIsProfitPack(base)) {
    return <div className="error-banner">逆向 DCF 参数包仍是旧的收入版。请重启 workbench 后刷新页面，确保接口返回 NOPAT 利润增速字段。</div>;
  }
  return <ReverseDcfTool base={base} />;
}

function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <div className="empty-state">
      <h2>{title}</h2>
      <p>{body}</p>
    </div>
  );
}

const QUARTERS = ["Q1", "Q2", "Q3", "Q4"] as const;

const STATE_LABELS: Record<string, string> = {
  actual: "① 实际",
  inherit: "② 默认季节性",
  manual: "③ 人工",
  q4: "④ Q4",
};

type QuarterlyDriverOption = {
  key: string;
  field: string;
  param: string;
  label: string;
  step: string;
  displayField: string;
  format: "percent" | "number";
};

const QUARTERLY_DRIVER_OPTIONS: QuarterlyDriverOption[] = [
  { key: "revenue_yoy", field: "revenue", param: "revenue_yoy", label: "收入同比", step: "0.01", displayField: "revenue_yoy", format: "percent" },
  { key: "gpm", field: "oper_cost", param: "gpm", label: "毛利率", step: "0.01", displayField: "gross_margin", format: "percent" },
  { key: "sell_exp_rate", field: "sell_exp", param: "sell_exp_rate", label: "销售费用率", step: "0.01", displayField: "sell_exp_rate", format: "percent" },
  { key: "admin_exp_rate", field: "admin_exp", param: "admin_exp_rate", label: "管理费用率", step: "0.01", displayField: "admin_exp_rate", format: "percent" },
  { key: "rd_exp_rate", field: "rd_exp", param: "rd_exp_rate", label: "研发费用率", step: "0.01", displayField: "rd_exp_rate", format: "percent" },
  { key: "biz_tax_surchg_rate", field: "biz_tax_surchg", param: "biz_tax_surchg_rate", label: "税附加率", step: "0.001", displayField: "biz_tax_surchg_rate", format: "percent" },
  { key: "fin_exp_abs", field: "fin_exp", param: "fin_exp_abs", label: "财务费用额", step: "1", displayField: "fin_exp", format: "number" },
  { key: "income_tax_rate", field: "income_tax", param: "income_tax_rate", label: "所得税率", step: "0.01", displayField: "income_tax_rate", format: "percent" },
];

type QuarterlyEdit = {
  row: QuarterlyRow;
  period: string;
  param: string;
  value: string;
};

function periodQuarterNumber(period: string): number {
  const match = period.match(/Q([1-4])$/);
  return match ? Number(match[1]) : 0;
}

function periodYear(period: string): number | null {
  const match = period.match(/^(\d{4})Q[1-4]$/);
  return match ? Number(match[1]) : null;
}

function periodLabel(period: string): string {
  const match = period.match(/^(\d{4})Q([1-4])$/);
  return match ? `${match[2]}Q${match[1]}` : period;
}

function periodBoundaryClass(period: string): string {
  const quarter = periodQuarterNumber(period);
  if (quarter === 1) return "year-start";
  if (quarter === 4) return "year-end";
  return "";
}

function formatQuarterlyValue(row: QuarterlyRow, value: number | null | undefined): string {
  if (row.format === "percent") return formatPercent(value, 1);
  return formatNumber(value);
}

function editableAssumptionOption(row: QuarterlyRow, period: string, viewYear: number): QuarterlyDriverOption | null {
  const option = QUARTERLY_DRIVER_OPTIONS.find((item) => item.displayField === row.field);
  if (!option) return null;
  const state = row.states[period];
  const quarter = periodQuarterNumber(period);
  if (periodYear(period) !== viewYear || quarter === 4 || state === "actual" || state === "q4") return null;
  return option;
}

function parseQuarterlyInput(raw: string, option: QuarterlyDriverOption): number | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  if (option.format === "percent") {
    const hasPercent = trimmed.endsWith("%");
    const normalized = trimmed.replace("%", "").replace(/,/g, "");
    const numeric = Number(normalized);
    if (!Number.isFinite(numeric)) return null;
    return hasPercent || Math.abs(numeric) > 1 ? numeric / 100 : numeric;
  }
  const numeric = Number(trimmed.replace(/,/g, ""));
  return Number.isFinite(numeric) ? numeric : null;
}

function quarterlyInputPlaceholder(option: QuarterlyDriverOption): string {
  return option.format === "percent" ? "0.02 / 2%" : "百万元";
}

function QuarterlyTable({ companyId, initialView }: { companyId: string; initialView?: QuarterlyView | null }) {
  const [view, setView] = useState<QuarterlyView | null | undefined>(initialView);
  const [edit, setEdit] = useState<QuarterlyEdit | null>(null);
  const [drawerPeriod, setDrawerPeriod] = useState<string | null>(null);
  const [drawerDrafts, setDrawerDrafts] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setView(initialView);
  }, [initialView]);

  const editableAssumptionPeriods = view
    ? QUARTERS.slice(0, 3)
        .map((quarter) => `${view.year}${quarter}`)
        .filter((period) => {
          const state = view.period_states?.[period] ?? view.quarter_states[String(periodQuarterNumber(period))] ?? "inherit";
          return state !== "actual" && state !== "q4";
        })
    : [];

  if (!view) return <EmptyState title="无季度视图" body="forecast_is.csv 或 data.db 暂不可用。" />;

  const periods = view.periods?.length ? view.periods : QUARTERS.map((quarter) => `${view.year}${quarter}`);
  const visibleRows = view.rows.filter((row) => !row.is_zero);
  const yearGroups = periods.reduce<Array<{ year: string; periods: string[] }>>((groups, period) => {
    const year = String(periodYear(period) ?? "");
    const last = groups[groups.length - 1];
    if (last?.year === year) {
      last.periods.push(period);
    } else {
      groups.push({ year, periods: [period] });
    }
    return groups;
  }, []);
  const firstPeriodYear = periodYear(periods[0] ?? "") ?? view.year;
  const lastPeriodYear = periodYear(periods[periods.length - 1] ?? "") ?? view.year;
  const timeRangeLabel = firstPeriodYear === lastPeriodYear ? String(view.year) : `${firstPeriodYear}-${lastPeriodYear}`;

  const saveOverride = async (period: string, param: string, rawValue: string, option: QuarterlyDriverOption) => {
    const numericValue = parseQuarterlyInput(rawValue, option);
    if (numericValue == null) {
      setError("请输入有效数字");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const result = await apiPutJson<{ ok: boolean; view: QuarterlyView }>(
        `/api/companies/${encodeURIComponent(companyId)}/quarterly/override`,
        { period, param, value: numericValue },
      );
      setView(result.view);
      setEdit(null);
      setDrawerDrafts((drafts) => {
        const next = { ...drafts };
        delete next[`${period}:${param}`];
        return next;
      });
    } catch (err) {
      setError(String(err));
    } finally {
      setSaving(false);
    }
  };

  const openEdit = (row: QuarterlyRow, period: string) => {
    const option = editableAssumptionOption(row, period, view.year);
    if (!option) return;
    setError(null);
    setEdit({ row, period, param: option.param, value: formatQuarterlyValue(row, row.values[period]) });
  };

  const saveEdit = async () => {
    if (!edit) return;
    const option = QUARTERLY_DRIVER_OPTIONS.find((item) => item.param === edit.param);
    if (!option) return;
    await saveOverride(edit.period, edit.param, edit.value, option);
  };

  const clearPeriod = async (period: string) => {
    setSaving(true);
    setError(null);
    try {
      const result = await apiDelete<{ ok: boolean; view: QuarterlyView }>(
        `/api/companies/${encodeURIComponent(companyId)}/quarterly/override/${period}`,
      );
      setView(result.view);
      setEdit(null);
      setDrawerDrafts({});
    } catch (err) {
      setError(String(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="view-stack">
      <section className="card quarterly-panel">
        <div className="section-heading compact">
          <div>
            <div className="eyebrow">Quarterly tracking · 百万元</div>
            <h2>{timeRangeLabel} 季度利润表追踪</h2>
          </div>
          <div className="quarter-state-row">
            {QUARTERS.map((quarter) => {
              const key = String(periodQuarterNumber(`${view.year}${quarter}`));
              const state = view.quarter_states[key] ?? "inherit";
              return (
                <span className={`quarter-state state-${state}`} key={quarter}>
                  {quarter} · {STATE_LABELS[state] ?? state}
                </span>
              );
            })}
          </div>
        </div>
        {error ? <div className="error-banner compact-error">{error}</div> : null}
        {view.q4_flags.length ? (
          <div className="q4-flag-strip">
            {view.q4_flags.map((flag) => (
              <span key={flag.ratio}>{flag.ratio}: {formatPercent(flag.implied, 1)}</span>
            ))}
          </div>
        ) : null}
        <div className="table-scroll workbook-scroll quarterly-scroll">
          <table className="financial-table statement-table quarterly-table">
            <thead>
              <tr>
                <th className="quarter-axis-corner"></th>
                {yearGroups.map((group) => (
                  <th className={`numeric quarter-year-head ${Number(group.year) === view.year ? "forecast-year" : "history-year"}`} colSpan={group.periods.length} key={group.year}>
                    {group.year}
                  </th>
                ))}
                <th className="numeric annual-head">年度</th>
              </tr>
              <tr>
                <th className="quarter-subhead-label">科目</th>
                {periods.map((period) => {
                  const periodState = view.period_states?.[period] ?? view.quarter_states[String(periodQuarterNumber(period))] ?? "inherit";
                  const canOpenDrawer = editableAssumptionPeriods.includes(period);
                  return (
                    <th className={`numeric quarter-period-head ${periodYear(period) === view.year ? "forecast-year" : "history-year"} ${periodBoundaryClass(period)}`} key={period}>
                      {canOpenDrawer ? (
                        <button className={`quarter-period-button state-${periodState}`} onClick={() => setDrawerPeriod(period)} type="button">
                          <span>{periodLabel(period)}</span>
                          <small>{STATE_LABELS[periodState] ?? periodState}</small>
                        </button>
                      ) : (
                        periodLabel(period)
                      )}
                    </th>
                  );
                })}
                <th className="numeric quarter-period-head annual-head">年度</th>
              </tr>
            </thead>
            <tbody>
              {visibleRows.map((row) => {
                const rowClass = row.role === "total" ? "total" : row.role === "metric" ? "metric" : row.category === "subtotal" ? "subtotal" : "normal";
                return (
                  <tr className={`${rowClass} ${QUARTERLY_KEY_ROWS.has(row.field) ? "key-row" : ""} ${row.highlight ? "highlight-row" : ""}`} key={row.field}>
                    <td className="statement-label" title={`${row.label} (${row.field})`}><span>{row.label}</span></td>
                    {periods.map((period) => {
                      const value = row.values[period];
                      const state = row.states[period] ?? view.period_states?.[period] ?? "inherit";
                      const editableOption = editableAssumptionOption(row, period, view.year);
                      const isEditing = edit?.row.field === row.field && edit.period === period;
                      return (
                        <td className={`numeric quarter-cell state-${state} ${periodYear(period) === view.year ? "forecast-year" : "history-year"} ${periodBoundaryClass(period)} ${typeof value === "number" && value < 0 ? "negative" : ""}`} key={`${row.field}-${period}`}>
                          {isEditing && editableOption ? (
                            <span className="quarter-inline-editor">
                              <input
                                autoFocus
                                inputMode="decimal"
                                onChange={(event) => {
                                  setError(null);
                                  setEdit({ ...edit, value: event.currentTarget.value });
                                }}
                                onKeyDown={(event) => {
                                  if (event.key === "Enter") void saveEdit();
                                  if (event.key === "Escape") setEdit(null);
                                }}
                                onFocus={(event) => event.currentTarget.select()}
                                placeholder={formatQuarterlyValue(row, value)}
                                type="text"
                                value={edit.value}
                              />
                              <button disabled={saving} onClick={saveEdit} type="button">OK</button>
                            </span>
                          ) : editableOption ? (
                            <button className={`quarter-cell-button assumption-editable-cell ${state === "manual" ? "is-manual" : ""}`} onClick={() => openEdit(row, period)} type="button">
                              {formatQuarterlyValue(row, value)}
                            </button>
                          ) : (
                            formatQuarterlyValue(row, value)
                          )}
                        </td>
                      );
                    })}
                    <td className={`numeric annual-cell ${typeof view.annual[row.field] === "number" && (view.annual[row.field] ?? 0) < 0 ? "negative" : ""}`}>
                      {formatQuarterlyValue(row, view.annual[row.field])}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
      {drawerPeriod ? (
        <div className="quarter-drawer-backdrop" role="presentation" onMouseDown={() => setDrawerPeriod(null)}>
          <aside className="quarter-drawer" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}>
            <div className="quarter-drawer-head">
              <div>
                <div className="eyebrow">
                  {periodLabel(drawerPeriod)} · {STATE_LABELS[view.period_states?.[drawerPeriod] ?? "inherit"] ?? "② 默认季节性"}
                </div>
                <h2>季度假设</h2>
              </div>
              <button className="secondary-button icon-button" onClick={() => setDrawerPeriod(null)} type="button">×</button>
            </div>
            <div className="quarter-drawer-list">
              {QUARTERLY_DRIVER_OPTIONS.map((option) => {
                const row = view.rows.find((item) => item.field === option.displayField);
                const draftKey = `${drawerPeriod}:${option.param}`;
                const currentValue = row ? row.values[drawerPeriod] : null;
                return (
                  <div className="quarter-drawer-row" key={option.key}>
                    <div className="quarter-drawer-row-copy">
                      <strong>{option.label}</strong>
                      <span>{row ? formatQuarterlyValue(row, currentValue) : "-"}</span>
                    </div>
                    <input
                      inputMode="decimal"
                      onChange={(event) => {
                        setError(null);
                        setDrawerDrafts((drafts) => ({ ...drafts, [draftKey]: event.currentTarget.value }));
                      }}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") void saveOverride(drawerPeriod, option.param, drawerDrafts[draftKey] ?? "", option);
                        if (event.key === "Escape") setDrawerDrafts((drafts) => ({ ...drafts, [draftKey]: "" }));
                      }}
                      placeholder={quarterlyInputPlaceholder(option)}
                      type="text"
                      value={drawerDrafts[draftKey] ?? ""}
                    />
                    <button
                      className="secondary-button"
                      disabled={saving || !(drawerDrafts[draftKey] ?? "").trim()}
                      onClick={() => saveOverride(drawerPeriod, option.param, drawerDrafts[draftKey] ?? "", option)}
                      type="button"
                    >
                      保存
                    </button>
                  </div>
                );
              })}
            </div>
            <div className="quarter-drawer-actions">
              <button
                className="secondary-button"
                disabled={saving || (view.period_states?.[drawerPeriod] ?? "inherit") !== "manual"}
                onClick={() => clearPeriod(drawerPeriod)}
                type="button"
              >
                清回默认季节性
              </button>
            </div>
          </aside>
        </div>
      ) : null}
    </div>
  );
}

function DetailView({
  detail,
  tab,
}: {
  detail: CompanyDetail;
  tab: TabKey;
}) {
  if (tab === "overview") return <Overview detail={detail} />;
  if (tab === "statements") return <StatementsView detail={detail} />;
  if (tab === "quarterly") return <QuarterlyTable companyId={detail.summary.id} initialView={detail.quarterly_view} />;
  if (tab === "yaml1") {
    return (
      <YamlWorkbook
        companyId={detail.summary.id}
        initialPresentation={detail.yaml1_presentation}
        path={detail.yaml1_path}
        revenueView={detail.yaml1_revenue_view}
        statementSheets={detail.statement_sheets}
        fullStatementSheets={detail.full_statement_sheets}
        stashView={detail.yaml1_stash_view}
        displayContract={detail.yaml1_display_contract}
        assumptionsView={detail.yaml1_assumptions_view}
        editableAssumptions={detail.editable_assumptions}
        annualRevenueBreakdown={detail.annual_revenue_breakdown}
        yaml1Text={detail.yaml1_text}
      />
    );
  }
  if (tab === "dcf") return <DcfView detail={detail} />;
  if (tab === "reverse") return <ReverseDcfView detail={detail} />;
  if (tab === "da" && detail.da_view) return <DaSchedule detail={detail} />;
  return <Overview detail={detail} />;
}

const STAGE_TONE: Record<PipelineStage, string> = {
  "未初始化": "stage-0",
  "初始化完毕": "stage-1",
  "预加载完毕": "stage-2",
  "建模完毕": "stage-3",
  "建模完毕且有DA表": "stage-4",
};

const fmtMv = (v: number | null | undefined) =>
  typeof v === "number" && !Number.isNaN(v) ? formatYiFromMillion(v, 0) : "—";
const fmtYoy = (v: number | null | undefined) =>
  typeof v === "number" && !Number.isNaN(v) ? formatSignedPercent(v, 1) : "—";
const fmtPe = (v: number | null | undefined) => {
  if (typeof v !== "number" || Number.isNaN(v)) return "—";
  const digits = v < 0 || v >= 15 ? 0 : 1;
  return formatMultiple(v, digits);
};

function homeToday(): string {
  try {
    return new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "long", day: "numeric" }).format(new Date());
  } catch {
    return "";
  }
}

const UNCLASSIFIED_SECTOR = "未分类";

function getSector(code: string, industry: IndustryData): string {
  const name = industry.companies[code];
  if (!name) return UNCLASSIFIED_SECTOR;
  if (!industry.sectors_order.includes(name)) return UNCLASSIFIED_SECTOR;
  return name;
}

function sortCompaniesByIndustry(companies: CompanySummary[], industry: IndustryData): CompanySummary[] {
  return [...companies].sort((a, b) => {
    const sectorA = getSector(a.code, industry);
    const sectorB = getSector(b.code, industry);
    if (sectorA === UNCLASSIFIED_SECTOR && sectorB !== UNCLASSIFIED_SECTOR) return -1;
    if (sectorB === UNCLASSIFIED_SECTOR && sectorA !== UNCLASSIFIED_SECTOR) return 1;
    const rankA = industry.sectors_order.indexOf(sectorA);
    const rankB = industry.sectors_order.indexOf(sectorB);
    if (rankA !== rankB) return rankA - rankB;
    const mvA = a.market_cap ?? -Infinity;
    const mvB = b.market_cap ?? -Infinity;
    if (mvB !== mvA) return mvB - mvA;
    return a.name.localeCompare(b.name, "zh-CN");
  });
}

type GroupedRowContext = {
  displayYear: number;
  nextYear: number;
  archiving: string | "__all__" | null;
  openFolder: (companyId: string) => Promise<void>;
  onSelectCompany: (companyId: string) => void;
};

function renderGroupedRows(
  rows: HomeFolderOverview[],
  industry: IndustryData,
  onIndustryChange: (next: IndustryData) => Promise<void>,
  ctx: GroupedRowContext,
) {
  const { displayYear, nextYear, archiving, openFolder, onSelectCompany } = ctx;
  if (rows.length === 0) {
    return (
      <tr>
        <td colSpan={11} className="home-empty">暂无覆盖公司。在 companies/ 下新建公司目录后将自动出现。</td>
      </tr>
    );
  }

  const order = new Map<string, number>();
  industry.sectors_order.forEach((sector, index) => order.set(sector, index));

  function sectorRank(code: string) {
    const sector = getSector(code, industry);
    if (sector === UNCLASSIFIED_SECTOR) return -1;
    return order.get(sector) ?? Number.MAX_SAFE_INTEGER;
  }

  const sorted = [...rows].sort((a, b) => {
    const rankA = sectorRank(a.code);
    const rankB = sectorRank(b.code);
    if (rankA !== rankB) return rankA - rankB;
    const mvA = a.signals?.forecast?.market_cap ?? -Infinity;
    const mvB = b.signals?.forecast?.market_cap ?? -Infinity;
    return mvB - mvA;
  });

  const groups: { sector: string; rows: HomeFolderOverview[] }[] = [];
  for (const row of sorted) {
    const sector = getSector(row.code, industry);
    const last = groups[groups.length - 1];
    if (last && last.sector === sector) {
      last.rows.push(row);
    } else {
      groups.push({ sector, rows: [row] });
    }
  }

  async function handleDropSector(targetSector: string, draggedSector: string) {
    if (targetSector === draggedSector) return;
    const next = { ...industry, sectors_order: [...industry.sectors_order] };
    const draggedIndex = next.sectors_order.indexOf(draggedSector);
    const targetIndex = next.sectors_order.indexOf(targetSector);
    if (draggedIndex === -1 || targetIndex === -1) return;
    next.sectors_order.splice(draggedIndex, 1);
    next.sectors_order.splice(targetIndex, 0, draggedSector);
    await onIndustryChange(next);
  }

  async function handleAssignSector(code: string, sectorName: string) {
    const trimmed = sectorName.trim();
    const next: IndustryData = {
      version: industry.version,
      sectors_order: [...industry.sectors_order],
      companies: { ...industry.companies },
    };
    if (!trimmed || trimmed === UNCLASSIFIED_SECTOR) {
      delete next.companies[code];
    } else {
      next.companies[code] = trimmed;
      if (!next.sectors_order.includes(trimmed)) {
        next.sectors_order.push(trimmed);
      }
    }
    await onIndustryChange(next);
  }

  const out: React.ReactNode[] = [];
  let rowIndex = 0;
  for (const group of groups) {
    out.push(
      <SectorHeader
        key={`sector-${group.sector}`}
        sector={group.sector}
        count={group.rows.length}
        onDropSector={handleDropSector}
      />,
    );
    for (const r of group.rows) {
      const s = r.signals;
      const f = s?.forecast ?? null;
      const revY1v = f?.revenue_yoy[String(displayYear)] ?? null;
      const revY2v = f?.revenue_yoy[String(nextYear)] ?? null;
      const profY1v = f?.profit_yoy[String(displayYear)] ?? null;
      const profY2v = f?.profit_yoy[String(nextYear)] ?? null;
      out.push(
        <tr key={r.company_id} style={{ animationDelay: `${Math.min(rowIndex, 12) * 28}ms` }}>
          <td className="company-cell">
            <span className="company-name">{r.name}</span>
            <span className="company-code">{r.code}</span>
          </td>
          <td className="status-cell">
            {s ? <span className={`stage-pill ${STAGE_TONE[s.pipeline_stage]}`}>{s.pipeline_stage}</span> : "读取失败"}
          </td>
          <td className="sector-cell">
            <SectorPicker
              value={getSector(r.code, industry)}
              sectors={industry.sectors_order}
              onChange={(sector) => handleAssignSector(r.code, sector)}
            />
          </td>
          <td className="actions-cell">
            <button className="ghost-btn" onClick={() => onSelectCompany(r.company_id)} type="button">跳转页面</button>
            <button className="ghost-btn" onClick={() => openFolder(r.company_id)} type="button">打开目录</button>
          </td>
          <td className="numeric group-start col-bold">{fmtMv(f?.market_cap)}</td>
          <td className="numeric col-bold">{fmtPe(f?.pe[String(displayYear)] ?? null)}</td>
          <td className="numeric col-bold">{fmtPe(f?.pe[String(nextYear)] ?? null)}</td>
          <td className={`numeric group-start ${revY1v != null && revY1v < 0 ? "negative" : ""}`}>{fmtYoy(revY1v)}</td>
          <td className={`numeric ${revY2v != null && revY2v < 0 ? "negative" : ""}`}>{fmtYoy(revY2v)}</td>
          <td className={`numeric group-start ${profY1v != null && profY1v < 0 ? "negative" : ""}`}>{fmtYoy(profY1v)}</td>
          <td className={`numeric ${profY2v != null && profY2v < 0 ? "negative" : ""}`}>{fmtYoy(profY2v)}</td>
        </tr>,
      );
      rowIndex += 1;
    }
  }
  return out;
}

function SectorHeader({
  sector,
  count,
  onDropSector,
}: {
  sector: string;
  count: number;
  onDropSector: (targetSector: string, draggedSector: string) => void;
}) {
  const [dragOver, setDragOver] = useState(false);
  const isUnclassified = sector === UNCLASSIFIED_SECTOR;
  return (
    <tr
      className={`sector-header ${dragOver ? "drag-over" : ""}`}
      draggable={!isUnclassified}
      onDragStart={(event) => {
        event.dataTransfer.setData("text/plain", sector);
        event.dataTransfer.effectAllowed = "move";
      }}
      onDragOver={(event) => {
        event.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(event) => {
        event.preventDefault();
        setDragOver(false);
        const dragged = event.dataTransfer.getData("text/plain");
        if (dragged && dragged !== sector) {
          onDropSector(sector, dragged);
        }
      }}
    >
      <td colSpan={11}>
        <span className="sector-title">{sector} {count} 家</span>
      </td>
    </tr>
  );
}

function SectorPicker({
  value,
  sectors,
  onChange,
}: {
  value: string;
  sectors: string[];
  onChange: (sector: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value === UNCLASSIFIED_SECTOR ? "" : value);
  const selectRef = useRef<HTMLSelectElement>(null);

  useEffect(() => {
    if (editing && selectRef.current) {
      selectRef.current.focus();
    }
  }, [editing]);

  const apply = (next: string) => {
    onChange(next.trim());
    setEditing(false);
  };

  if (editing) {
    return (
      <div className="sector-picker">
        <select
          ref={selectRef}
          value={draft}
          onChange={(event) => apply(event.currentTarget.value)}
          onBlur={() => apply(draft)}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              setDraft(value === UNCLASSIFIED_SECTOR ? "" : value);
              setEditing(false);
            }
          }}
        >
          <option value="">未分类</option>
          {sectors.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
      </div>
    );
  }

  return (
    <button
      className={`sector-badge sector-badge-button ${value === UNCLASSIFIED_SECTOR ? "sector-unclassified" : ""}`}
      onClick={() => setEditing(true)}
      type="button"
    >
      {value === UNCLASSIFIED_SECTOR ? "选择行业" : value}
    </button>
  );
}

function ModelSettingsPanel({
  rows,
  industry,
  onIndustryChange,
  onArchiveAll,
  onClose,
  archiving,
}: {
  rows: HomeFolderOverview[];
  industry: IndustryData;
  onIndustryChange: (next: IndustryData) => Promise<void>;
  onArchiveAll: () => Promise<void>;
  onClose: () => void;
  archiving: boolean;
}) {
  const [newSector, setNewSector] = useState("");

  const staleCompanies = useMemo(() => {
    const stale: { name: string; code: string; date: string; days: number }[] = [];
    const today = new Date();
    for (const r of rows) {
      const d = r.signals?.yaml1_date;
      if (!d) continue;
      const then = new Date(`${d}T00:00:00`);
      const days = Math.floor((today.getTime() - then.getTime()) / (1000 * 60 * 60 * 24));
      if (days > 90) {
        stale.push({ name: r.name, code: r.code, date: d, days });
      }
    }
    stale.sort((a, b) => b.days - a.days);
    return stale;
  }, [rows]);

  const sectorCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const r of rows) {
      const sector = getSector(r.code, industry);
      counts[sector] = (counts[sector] ?? 0) + 1;
    }
    return counts;
  }, [rows, industry]);

  async function addSector() {
    const trimmed = newSector.trim();
    if (!trimmed || trimmed === UNCLASSIFIED_SECTOR) return;
    if (industry.sectors_order.includes(trimmed)) return;
    await onIndustryChange({
      ...industry,
      sectors_order: [...industry.sectors_order, trimmed],
    });
    setNewSector("");
  }

  async function removeSector(sector: string) {
    if (sector === UNCLASSIFIED_SECTOR) return;
    const count = sectorCounts[sector] ?? 0;
    if (count > 0) {
      if (!window.confirm(`删除行业“${sector}”会把 ${count} 家公司设为未分类，确认吗？`)) return;
    }
    const next: IndustryData = {
      version: industry.version,
      sectors_order: industry.sectors_order.filter((s) => s !== sector),
      companies: { ...industry.companies },
    };
    for (const [code, name] of Object.entries(next.companies)) {
      if (name === sector) delete next.companies[code];
    }
    await onIndustryChange(next);
  }

  return (
    <div className="tutorial-overlay" role="dialog" aria-modal="true" aria-label="模型设置区">
      <div className="tutorial-page config-page">
        <header className="tutorial-header">
          <div>
            <div className="eyebrow">Coverage settings</div>
            <h1>模型设置区</h1>
          </div>
          <button className="tutorial-close" onClick={onClose} type="button" aria-label="关闭">×</button>
        </header>

        <section className="tutorial-section">
          <h2>归档与同步</h2>
          <div className="model-settings-grid">
            {staleCompanies.length > 0 ? (
              <div className="model-settings-card model-settings-warning">
                <span>太久没更新建模</span>
                <strong>{staleCompanies.length} 家公司超过 90 天未更新</strong>
                <ul className="stale-company-list">
                  {staleCompanies.map((c) => (
                    <li key={c.code}>
                      <b>{c.name}</b>
                      <span>{c.date}</span>
                      <em>已 {c.days} 天</em>
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              <div className="model-settings-card">
                <span>模型新鲜度</span>
                <strong>没有太久没更新的模型</strong>
                <p>所有已建模公司都在 90 天内更新过。</p>
              </div>
            )}
            <div className="model-settings-card">
              <span>一键归档</span>
              <button className="archive-btn" disabled={archiving} onClick={onArchiveAll} type="button">
                {archiving ? "归档中…" : "归档所有符合条件"}
              </button>
              <p>将 yaml1 旧版本、根目录旧 Excel 移入历史区；各留最新一份。</p>
            </div>
          </div>
        </section>

        <section className="tutorial-section">
          <h2>行业编辑区</h2>
          <div className="sector-manager">
            <div className="sector-manager-add">
              <input
                type="text"
                value={newSector}
                onChange={(event) => setNewSector(event.currentTarget.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") void addSector();
                }}
                placeholder="输入新行业名称"
              />
              <button className="secondary-button" onClick={() => void addSector()} type="button">增加行业</button>
            </div>
            <div className="sector-manager-list">
              {industry.sectors_order.length === 0 ? (
                <div className="sector-manager-empty">暂无行业，请在上方添加。</div>
              ) : (
                industry.sectors_order.map((sector) => (
                  <div className="sector-manager-row" key={sector}>
                    <span className="sector-manager-name">{sector}</span>
                    <span className="sector-manager-count">{sectorCounts[sector] ?? 0} 家</span>
                    <button className="ghost-btn" onClick={() => void removeSector(sector)} type="button">删除</button>
                  </div>
                ))
              )}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}

function FolderOverview({
  onOpenTutorial,
  industry,
  onIndustryChange,
  sortedCompanies,
  onSelectCompany,
}: {
  onOpenTutorial: () => void;
  industry: IndustryData;
  onIndustryChange: (next: IndustryData) => Promise<void>;
  sortedCompanies: CompanySummary[];
  onSelectCompany: (companyId: string) => void;
}) {
  const [rows, setRows] = useState<HomeFolderOverview[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const [archiving, setArchiving] = useState<string | "__all__" | null>(null);
  const [showSettings, setShowSettings] = useState(false);
  const [displayYear, setDisplayYear] = useState<number>(() => {
    const raw = window.localStorage.getItem("mka.home_display_start_year");
    return raw ? Number(raw) : 2026;
  });
  const nextYear = displayYear + 1;
  const displayYearShort = String(displayYear).slice(-2);
  const nextYearShort = String(nextYear).slice(-2);

  useEffect(() => {
    void (async () => {
      try {
        const settings = await apiGet<AppSettings>("/api/settings");
        const year = settings.home_display_start_year ?? 2026;
        setDisplayYear(year);
        window.localStorage.setItem("mka.home_display_start_year", String(year));
      } catch {
        // keep localStorage fallback
      }
    })();
  }, []);

  async function load() {
    try {
      const data = await apiGet<HomeFolderOverview[]>("/api/home/folder-overview");
      const ordered = sortCompaniesByIndustry(
        data.map((row) => ({ id: row.company_id, name: row.name, code: row.code, market_cap: row.signals?.forecast?.market_cap ?? null } as CompanySummary)),
        industry,
      );
      const orderMap = new Map(ordered.map((c, index) => [c.id, index]));
      const sortedRows = [...data].sort((a, b) => (orderMap.get(a.company_id) ?? 0) - (orderMap.get(b.company_id) ?? 0));
      setRows(sortedRows);
      setError(undefined);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    const id = window.setInterval(() => {
      if (document.visibilityState === "visible") void load();
    }, 3000);
    return () => window.clearInterval(id);
  }, [industry]);

  async function openFolder(companyId: string) {
    try {
      await apiPost<{ ok: boolean }>(`/api/companies/${encodeURIComponent(companyId)}/open-folder`);
    } catch (err) {
      setError(String(err));
    }
  }

  async function archive(companyId: string) {
    const msg = "一键归档历史模型？将：yaml1 旧版本移入 Agent/yaml1history、根目录旧 Excel 移入 Agent/Modelhistory、删除 ~$ 锁文件；各留最新一份。";
    if (!window.confirm(msg)) return;
    setArchiving(companyId);
    try {
      await apiPost<ArchiveModelsResult>(`/api/companies/${encodeURIComponent(companyId)}/archive-models`);
      await load();
    } catch (err) {
      setError(String(err));
    } finally {
      setArchiving(null);
    }
  }

  async function archiveAll() {
    const eligible = rows.filter((r) => r.signals && (r.signals.yaml1_archive_eligible || r.signals.root_models.archive_eligible));
    if (eligible.length === 0) return;
    if (!window.confirm(`确认归档 ${eligible.length} 家公司的历史模型？`)) return;
    setArchiving("__all__");
    try {
      for (const r of eligible) {
        await apiPost<ArchiveModelsResult>(`/api/companies/${encodeURIComponent(r.company_id)}/archive-models`);
      }
      await load();
    } catch (err) {
      setError(String(err));
    } finally {
      setArchiving(null);
    }
  }

  return (
    <div className="view-stack home-page">
      <header className="home-masthead">
        <div className="masthead-brand">
          <div className="masthead-wordmark">ModelKing</div>
          <div className="masthead-tagline">Buy-side equity research workbench</div>
        </div>
        <button className="tutorial-btn" onClick={onOpenTutorial} type="button">配置和教程</button>
      </header>

      <div className="home-section-header">
        <div>
          <div className="eyebrow">Coverage universe</div>
          <h2>公司覆盖与建模进度</h2>
        </div>
        <button className="tutorial-btn" onClick={() => setShowSettings(true)} type="button">模型设置区</button>
      </div>

      {error ? <div className="error-banner">{error}</div> : null}
      {loading ? (
        <div className="home-loading">
          <span className="home-loading-bar" />
          <span>Loading coverage</span>
        </div>
      ) : null}
      {!loading ? (
        <section className="home-table-card">
          <div className="table-scroll workbook-scroll">
            <table className="home-coverage-table">
              <thead>
                <tr className="home-header-row">
                  <th className="col-company">公司</th>
                  <th className="col-status">建模状态</th>
                  <th className="col-sector">行业</th>
                  <th className="col-actions">操作</th>
                  <th className="col-metric group-start col-bold">市值(亿)</th>
                  <th className="col-metric col-bold">{displayYearShort}E PE</th>
                  <th className="col-metric col-bold">{nextYearShort}E PE</th>
                  <th className="col-metric group-start">{displayYearShort}E 营收同比</th>
                  <th className="col-metric">{nextYearShort}E 营收同比</th>
                  <th className="col-metric group-start">{displayYearShort}E 利润同比</th>
                  <th className="col-metric">{nextYearShort}E 利润同比</th>
                </tr>
              </thead>
              <tbody>
                  {rows.length === 0 ? (
                  <tr>
                    <td colSpan={11} className="home-empty">暂无覆盖公司。在 companies/ 下新建公司目录后将自动出现。</td>
                  </tr>
                )                 : renderGroupedRows(rows, industry, onIndustryChange, {
                    displayYear,
                    nextYear,
                    archiving,
                    openFolder,
                    onSelectCompany,
                  })}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
      {showSettings ? (
        <ModelSettingsPanel
          rows={rows}
          industry={industry}
          onIndustryChange={onIndustryChange}
          onArchiveAll={archiveAll}
          onClose={() => setShowSettings(false)}
          archiving={archiving === "__all__"}
        />
      ) : null}
    </div>
  );
}

export default function App() {
  const [companies, setCompanies] = useState<CompanySummary[]>([]);
  const [selectedId, setSelectedId] = useState<string>();
  const [detail, setDetail] = useState<CompanyDetail>();
  const [tab, setTab] = useState<TabKey>("overview");
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string>();
  const [showTutorial, setShowTutorial] = useState(false);
  const [homeActive, setHomeActive] = useState(true);
  const [industry, setIndustry] = useState<IndustryData>({ version: 1, sectors_order: [], companies: {} });
  const [industryLoading, setIndustryLoading] = useState(true);

  async function loadIndustry() {
    setIndustryLoading(true);
    try {
      const result = await apiGet<IndustryData>("/api/industry");
      setIndustry(result);
    } catch (err) {
      setError(String(err));
    } finally {
      setIndustryLoading(false);
    }
  }

  async function saveIndustry(next: IndustryData) {
    try {
      const result = await apiPutJson<IndustryData>("/api/industry", next as Record<string, unknown>);
      setIndustry(result);
    } catch (err) {
      setError(String(err));
      throw err;
    }
  }

  const sortedCompanies = useMemo(() => sortCompaniesByIndustry(companies, industry), [companies, industry]);

  async function loadCompanies() {
    setLoading(true);
    setError(undefined);
    try {
      const result = await apiGet<CompanySummary[]>("/api/companies");
      setCompanies(result);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }

  async function loadDetail(id: string) {
    setDetailLoading(true);
    setError(undefined);
    try {
      const result = await apiGet<CompanyDetail>(`/api/companies/${encodeURIComponent(id)}`);
      setDetail(result);
    } catch (err) {
      setError(String(err));
    } finally {
      setDetailLoading(false);
    }
  }

  async function regenerateForecast() {
    if (!detail?.summary.id) return;
    setRunning(true);
    setError(undefined);
    try {
      const result = await apiPost<{ ok: boolean; stdout: string; stderr: string }>(`/api/companies/${encodeURIComponent(detail.summary.id)}/forecast`);
      if (!result.ok) throw new Error(result.stderr || result.stdout || "Forecast failed");
      await loadCompanies();
      await loadDetail(detail.summary.id);
    } catch (err) {
      setError(String(err));
    } finally {
      setRunning(false);
    }
  }

  useEffect(() => {
    void loadCompanies();
    void loadIndustry();
  }, []);

  useEffect(() => {
    if (selectedId) void loadDetail(selectedId);
  }, [selectedId]);

  const selectedCompany = companies.find((company) => company.id === selectedId);
  const headerStats = selectedCompany
    ? [
        ["VALUE", formatNumber(statValue(selectedCompany, "per_share_value"))],
        ["UPDATED", formatDate(selectedCompany.updated_at)],
      ]
    : [];

  return (
    <div className="app-shell">
      <Sidebar
        companies={sortedCompanies}
        loading={loading || industryLoading}
        onSelect={(id) => { setSelectedId(id); setHomeActive(false); }}
        selectedId={selectedId}
        homeActive={homeActive}
        onSelectHome={() => { setHomeActive(true); setSelectedId(undefined); }}
      />
      <main className="main-pane">
        {homeActive ? (
          <FolderOverview
            onOpenTutorial={() => setShowTutorial(true)}
            industry={industry}
            onIndustryChange={saveIndustry}
            sortedCompanies={sortedCompanies}
            onSelectCompany={(id) => { setSelectedId(id); setHomeActive(false); }}
          />
        ) : (
          <>
            <header className="topbar">
              <div>
                <div className="eyebrow">Workbench</div>
                <h1>{selectedCompany?.name ?? "Company folder"}</h1>
              </div>
              <div className="topbar-right">
                <div className="topbar-stats">
                  {headerStats.map(([label, value]) => (
                    <div className="topbar-stat" key={label}>
                      <span>{label}</span>
                      <strong>{value}</strong>
                    </div>
                  ))}
                </div>
                <button className="tutorial-btn" onClick={() => setShowTutorial(true)} type="button">配置和教程</button>
              </div>
            </header>

            <nav className="tabbar">
              {tabs.filter((item) => item.key !== "da" || Boolean(detail?.da_view)).map((item) => (
                <button className={tab === item.key ? "active" : ""} key={item.key} onClick={() => setTab(item.key)} type="button">
                  {item.label}
                </button>
              ))}
            </nav>

            {error ? <div className="error-banner">{error}</div> : null}
            {detailLoading ? <div className="activity content-activity">Loading company model</div> : null}
            {!detailLoading && detail ? <DetailView detail={detail} tab={tab} /> : null}
            {!detailLoading && !detail && !error ? <EmptyState title="No company selected" body="Select a company from the sidebar to inspect its model folder." /> : null}
          </>
        )}
      </main>
      {showTutorial ? <Tutorial onClose={() => setShowTutorial(false)} onSaved={loadCompanies} /> : null}
    </div>
  );
}
