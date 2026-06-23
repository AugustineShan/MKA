import { Fragment, useEffect, useMemo, useState } from "react";
import type {
  AnnualRevenueBreakdownRow,
  AssumptionPatch,
  AssumptionPreview,
  AssumptionsKnob,
  CompanyDetail,
  CompanySummary,
  DcfDetailRow,
  EditableAssumption,
  EditableAssumptionCell,
  FileItem,
  QuarterlyRow,
  QuarterlyView,
  StashBlock,
  StatementRow,
  StatementSheet,
  TabKey,
  TerminalView,
  Yaml1AssumptionsView,
  Yaml1Presentation,
  Yaml1RevenueSegment,
  Yaml1RevenueView,
} from "./types";

const tabs: Array<{ key: TabKey; label: string }> = [
  { key: "overview", label: "Overview" },
  { key: "yaml1", label: "核心假设展示" },
  { key: "statements", label: "完整三表" },
  { key: "dcf", label: "DCF" },
  { key: "quarterly", label: "季度展示" },
  { key: "materials", label: "Materials" },
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
  previewSummary?: Record<string, unknown> | null,
): Promise<{ prompt: string }> {
  return apiPostJson<{ prompt: string }>(
    `/api/companies/${encodeURIComponent(companyId)}/assumption-brief`,
    { patches, preview_summary: previewSummary ?? null },
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

function calcCagr(start: number, end: number | undefined, periods: number): number | null {
  if (!end || start <= 0 || periods <= 0) return null;
  return (end / start) ** (1 / periods) - 1;
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
}: {
  companies: CompanySummary[];
  selectedId?: string;
  onSelect: (id: string) => void;
  loading: boolean;
}) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-title">ModelKing</div>
        <div className="brand-subtitle">Buy-side workbench</div>
      </div>
      <div className="sidebar-section-label">Companies</div>
      <div className="company-list">
        {loading ? <div className="activity">Loading companies</div> : null}
        {companies.map((company) => (
          <button
            className={`company-item ${selectedId === company.id ? "selected" : ""}`}
            key={company.id}
            onClick={() => onSelect(company.id)}
            type="button"
          >
            <span className="company-name">{company.name}</span>
            <span className="company-code">{company.code}</span>
          </button>
        ))}
      </div>
    </aside>
  );
}

function StatusPill({ label, tone = "neutral" }: { label: string; tone?: "neutral" | "blue" | "red" }) {
  return <span className={`status-pill ${tone}`}>{label}</span>;
}

function MetricCard({ label, value, caption }: { label: string; value: string; caption?: string }) {
  return (
    <div className="metric-card">
      <div className="eyebrow">{label}</div>
      <div className="metric-value">{value}</div>
      {caption ? <div className="metric-caption">{caption}</div> : null}
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="info-row">
      <div className="info-label">{label}</div>
      <div className="info-value">{value}</div>
    </div>
  );
}

function Overview({ detail, running, onRun }: { detail: CompanyDetail; running: boolean; onRun: () => void }) {
  const { summary, dcf_summary: dcf, manifest } = detail;
  return (
    <div className="view-stack">
      <section className="hero-block">
        <div>
          <div className="eyebrow">Company model</div>
          <h1>{summary.name}</h1>
          <div className="hero-meta">
            <span>{summary.ticker ?? summary.code}</span>
            <span>{summary.path}</span>
          </div>
        </div>
        <button className="primary-button" disabled={running} onClick={onRun} type="button">
          {running ? "Running" : "Regenerate DCF"}
        </button>
      </section>

      <section className="metric-grid">
        <MetricCard label="Per-share value" value={formatNumber(dcf?.per_share_value ?? summary.per_share_value)} caption="DCF output" />
        <MetricCard label="Base period" value={String(dcf?.base_period ?? summary.base_period ?? "-")} />
        <MetricCard label="Forecast years" value={String(dcf?.forecast_years ?? summary.forecast_years ?? "-")} />
        <MetricCard label="Warnings" value={String(manifest?.warnings_count ?? summary.warnings_count ?? 0)} />
      </section>

      <section className="card">
        <div className="section-heading">
          <div>
            <div className="eyebrow">Run contract</div>
            <h2>defaults.yaml + yaml1_*.yaml -&gt; forecast/</h2>
          </div>
          <div className="pill-row">
            <StatusPill label={summary.has_defaults ? "YAML2 ready" : "Missing YAML2"} tone={summary.has_defaults ? "blue" : "red"} />
            <StatusPill label={summary.has_yaml1 ? "YAML1 ready" : "Missing YAML1"} tone={summary.has_yaml1 ? "blue" : "red"} />
            <StatusPill label={summary.backtest_status ?? "No backtest"} />
          </div>
        </div>
        <div className="manifest-grid">
          <InfoRow label="Last run" value={formatDate(summary.updated_at)} />
          <InfoRow label="YAML1" value={String(manifest?.yaml1_path ?? detail.yaml1_path ?? "-")} />
          <InfoRow label="YAML2" value={String(manifest?.yaml2_defaults_path ?? "defaults.yaml")} />
          <InfoRow label="Forecast" value={String(manifest?.output_dir ?? "forecast/")} />
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

function StashBlockView({ block, depth = 0 }: { block: StashBlock; depth?: number }) {
  const open = block.type === "series_table" || block.type === "attr_table";
  return (
    <details className={`stash-block depth-${depth}`} open={open}>
      <summary className="stash-block-header">
        <span className="stash-block-name">{block.name}</span>
        <span className="stash-type-badge">{STASH_TYPE_LABEL[block.type]}</span>
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

function buildStatementDisplayRows(sheet: StatementSheet, showZeroRows: boolean, showTechnicalRows: boolean, visibleYears: string[]): StatementDisplayRow[] {
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

function FullStatementTable({ sheet, basePeriod, showZeroRows, showTechnicalRows, years }: { sheet: StatementSheet; basePeriod: string; showZeroRows: boolean; showTechnicalRows: boolean; years?: string[] }) {
  const visibleYears = years ?? sheet.years;
  const historyYears = useMemo(() => {
    const base = Number(basePeriod);
    return new Set(visibleYears.filter((y) => (Number(y) || 0) <= base));
  }, [visibleYears, basePeriod]);
  const rows = useMemo(() => buildStatementDisplayRows(sheet, showZeroRows, showTechnicalRows, visibleYears), [sheet, showZeroRows, showTechnicalRows, visibleYears]);
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
  // signedDecimal=带符号同比% · volume=1位小数(万吨)
  format?: "int" | "num2" | "decimal" | "signedDecimal" | "volume";
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
              {g.rows.map((r, ri) => (
                <tr key={ri} className={`${r.bold ? "key-row" : ""} ${r.muted ? "muted-row" : ""} ${r.driver ? "driver-assumption-row" : ""}`}>
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
                              onChange={(event) => onInlineEditChange?.(event.currentTarget.value)}
                              onKeyDown={(event) => {
                                if (event.key === "Enter") onCommitInlineEdit?.(editable.assumption, editable.cell);
                                if (event.key === "Escape") onCancelInlineEdit?.();
                              }}
                              type="text"
                              value={inlineEdit?.raw ?? ""}
                            />
                            <button onClick={() => onCommitInlineEdit?.(editable.assumption, editable.cell)} type="button">OK</button>
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
              ))}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── 区域分组构建器 ──

function knobLabel(k: AssumptionsKnob): string {
  return k.src.replace(/^#/, "").replace(/\(.*\)$/, "").trim() || k.path;
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

const REVENUE_DRIVER_LABELS: Record<string, string> = {
  volume: "销量增速",
  price: "吨价增速",
  revenue_yoy: "营收增速",
  margin: "毛利率",
};

function revenueDriversForSegment(editable: EditableAssumption[], segmentName: string): EditableAssumption[] {
  const prefix = `income.revenue.${segmentName}.`;
  const rank: Record<string, number> = { revenue_yoy: 0, volume: 1, price: 2, margin: 3 };
  return editable
    .filter((row) => row.group === "revenue_driver" && row.path.startsWith(prefix))
    .sort((a, b) => (rank[revenueDriverKey(a, segmentName)] ?? 99) - (rank[revenueDriverKey(b, segmentName)] ?? 99) || a.label.localeCompare(b.label, "zh-Hans-CN"));
}

function revenueDriverKey(row: EditableAssumption, segmentName: string): string {
  const prefix = `income.revenue.${segmentName}.`;
  return row.path.startsWith(prefix) ? row.path.slice(prefix.length) : (row.family ?? "");
}

function revenueDriverAxisRow(row: EditableAssumption, segmentName: string): AxisRow {
  const values: Record<string, number | null> = {};
  for (const cell of row.cells) values[cell.year] = cell.value;
  const key = revenueDriverKey(row, segmentName);
  const label = REVENUE_DRIVER_LABELS[key] ?? row.label.replace(`${segmentName} · `, "");
  return {
    label: `${segmentName} · ${label}`,
    values,
    note: [row.path, row.src, row.note].filter(Boolean).join("\n"),
    muted: true,
    driver: true,
    editablePath: row.path,
    format: editableAxisFormat(row),
  };
}

function buildRevenueGroups(
  view: Yaml1RevenueView,
  presentation: Yaml1Presentation | null | undefined,
  secondaryBlocks: StashBlock[],
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
    const segmentDrivers = revenueDriversForSegment(editable, seg.name);
    const revenueYoyDriver = segmentDrivers.find((row) => revenueDriverKey(row, seg.name) === "revenue_yoy");
    const inlineDriverRows = segmentDrivers.filter((row) => row !== revenueYoyDriver);
    const revValues: Record<string, number | null> = { ...(seg.history_revenues ?? {}), ...seg.revenues };
    segRows.push({ label: `${seg.name} · 收入`, values: revValues, note: seg.note, format: "int" });
    const yoyValues: Record<string, number | null> = { ...yoySeries(seg.history_revenues), ...seg.yoys };
    if (revenueYoyDriver) {
      for (const cell of revenueYoyDriver.cells) yoyValues[cell.year] = cell.value;
    }
    segRows.push({ label: `${seg.name} · 同比`, muted: true, values: yoyValues, format: "signedDecimal", editablePath: revenueYoyDriver?.path });
    if (seg.history_volumes || seg.volumes) {
      const volValues: Record<string, number | null> = { ...(seg.history_volumes ?? {}), ...(seg.volumes ?? {}) };
      segRows.push({ label: `${seg.name} · 销量(万吨)`, muted: true, values: volValues, format: "volume" });
    }
    for (const driver of inlineDriverRows) {
      segRows.push(revenueDriverAxisRow(driver, seg.name));
    }
  }
  groups.push({ title: "主拆分 · 业务线", unit: "百万元", rows: segRows });
  // 副拆分
  for (const b of secondaryBlocks) {
    const sub = b.name.replace(/^副拆分[_]?/, "") || b.name;
    groups.push({
      title: `副拆分 · ${sub}`,
      unit: b.unit,
      caveat: b.caveat,
      note: b.note,
      rows: b.items.filter(isSeriesItem).map((it) => ({ label: it.label, values: it.values, note: it.note, format: "int" })),
    });
  }
  return groups;
}

function buildAssumptionsGroups(view: Yaml1AssumptionsView): AxisGroup[] {
  return view.sections.map((sec) => ({
    title: sec.title,
    rows: sec.knobs.map((k) => {
      const values: Record<string, number | null> = {};
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
  if (row.format === "percent") return formatPercent(value, 2);
  if (row.format === "integer") return formatNumber(value, 0);
  return formatNumber(value, 2);
}

function editableInputValue(row: EditableAssumption, value: number | null): string {
  if (value == null) return "";
  const displayValue = row.format === "percent" ? value * 100 : value;
  return `${Number(displayValue.toFixed(6))}`;
}

function parseEditableInput(row: EditableAssumption, raw: string): number | null {
  const trimmed = raw.trim();
  if (trimmed === "") return null;
  const parsed = Number(trimmed.replace(/,/g, "").replace(/%$/, ""));
  if (!Number.isFinite(parsed)) return null;
  return row.format === "percent" ? parsed / 100 : parsed;
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
  if (row.format === "percent") return "decimal";
  if (row.format === "integer") return "int";
  return "num2";
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
        label: row.label,
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

function buildReferenceGroups(refBlocks: StashBlock[]): { groups: AxisGroup[]; rest: StashBlock[] } {
  const groups: AxisGroup[] = [];
  const rest: StashBlock[] = [];
  for (const b of refBlocks) {
    if (blockIsYearSeries(b)) {
      groups.push({
        title: b.name,
        unit: b.unit,
        caveat: b.caveat,
        note: b.note,
        // 参考项单位混杂（百万元/pct/甚至同行不同单位如液体乳核对项），统一 2 位小数保留精度，单位在组头显示
        rows: b.items.filter(isSeriesItem).map((it) => ({ label: it.label, values: it.values, note: it.note, format: "num2" as const })),
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

const ANNUAL_SERIES_METRICS = [
  { key: "revenue_yuan", label: "收入" },
  { key: "revenue_pct", label: "占比" },
  { key: "revenue_yoy_pct", label: "同比" },
  { key: "gross_margin_pct", label: "毛利率" },
] as const;

type AnnualSeriesMetric = (typeof ANNUAL_SERIES_METRICS)[number]["key"];

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
  const allRows = rows ?? [];
  const years = useMemo(() => [...new Set(allRows.map((row) => row.year))].sort((a, b) => b - a), [allRows]);
  const seriesYears = useMemo(() => [...years].sort((a, b) => a - b), [years]);
  const [activeYear, setActiveYear] = useState<number | null>(years[0] ?? null);
  const [viewMode, setViewMode] = useState<"snapshot" | "series">("series");
  const [seriesMetric, setSeriesMetric] = useState<AnnualSeriesMetric>("revenue_yuan");

  useEffect(() => {
    if (!years.length) {
      setActiveYear(null);
      return;
    }
    setActiveYear((current) => (current && years.includes(current) ? current : years[0]));
  }, [years]);

  const yearRows = useMemo(() => allRows.filter((row) => row.year === activeYear), [allRows, activeYear]);
  const availableDimensions = useMemo(
    () => ANNUAL_DIMENSIONS.filter((dimension) => allRows.some((row) => row.dimension === dimension.key)),
    [allRows],
  );
  const [activeDimension, setActiveDimension] = useState<string>("product");

  useEffect(() => {
    if (!availableDimensions.length) return;
    setActiveDimension((current) =>
      availableDimensions.some((dimension) => dimension.key === current) ? current : availableDimensions[0].key,
    );
  }, [availableDimensions]);

  const visibleRows = useMemo(
    () =>
      yearRows
        .filter((row) => row.dimension === activeDimension)
        .sort((left, right) => (right.revenue_yuan ?? 0) - (left.revenue_yuan ?? 0)),
    [yearRows, activeDimension],
  );
  const dimensionRows = useMemo(() => allRows.filter((row) => row.dimension === activeDimension), [allRows, activeDimension]);
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
    return visibleRows.filter((row) => {
      const disclosed = normalizeDisclosureName(row.item_name);
      return normalizedModelNames.some((model) => disclosed.includes(model) || model.includes(disclosed));
    });
  }, [activeDimension, normalizedModelNames, visibleRows]);
  const matchRate = visibleRows.length ? matchedRows.length / visibleRows.length : null;
  const activeLabel = availableDimensions.find((dimension) => dimension.key === activeDimension)?.label ?? "披露口径";

  if (!allRows.length) {
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
            <span>展示</span>
            <strong>{viewMode === "snapshot" ? activeYear ?? "-" : "时间序列"}</strong>
          </div>
          <div>
            <span>维度</span>
            <strong>{activeLabel}</strong>
          </div>
          <div>
            <span>模型匹配</span>
            <strong>{matchRate == null ? "-" : formatPercent(matchRate, 0)}</strong>
          </div>
        </div>
      </div>

      <div className="annual-disclosure-controls">
        <div className="range-toggle annual-mode-toggle" role="group">
          <button className={viewMode === "snapshot" ? "active" : ""} onClick={() => setViewMode("snapshot")} type="button">
            单年结构
          </button>
          <button className={viewMode === "series" ? "active" : ""} onClick={() => setViewMode("series")} type="button">
            时间序列
          </button>
        </div>
        <div className="sheet-tabs compact-tabs" role="tablist">
          {years.map((year) => (
            <button className={viewMode === "snapshot" && year === activeYear ? "active" : ""} key={year} onClick={() => { setActiveYear(year); setViewMode("snapshot"); }} type="button">
              {year}
            </button>
          ))}
        </div>
        <div className="sheet-tabs compact-tabs" role="tablist">
          {availableDimensions.map((dimension) => (
            <button
              className={dimension.key === activeDimension ? "active" : ""}
              key={dimension.key}
              onClick={() => setActiveDimension(dimension.key)}
              type="button"
            >
              <span>{dimension.label}</span>
              <small>{allRows.filter((row) => row.dimension === dimension.key).length}</small>
            </button>
          ))}
        </div>
        {viewMode === "series" ? (
          <div className="sheet-tabs compact-tabs" role="tablist">
            {ANNUAL_SERIES_METRICS.map((metric) => (
              <button className={seriesMetric === metric.key ? "active" : ""} key={metric.key} onClick={() => setSeriesMetric(metric.key)} type="button">
                {metric.label}
              </button>
            ))}
          </div>
        ) : null}
      </div>

      {viewMode === "series" && seriesItems.length ? (
        <div className="table-scroll workbook-scroll annual-series-table-wrap">
          <table className="financial-table annual-series-table">
            <thead>
              <tr>
                <th>{activeLabel}</th>
                {seriesYears.map((year) => (
                  <th className="numeric" key={year}>{year}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {seriesItems.map((item) => (
                <tr key={item.name}>
                  <td className="statement-label">
                    <span>{item.name}</span>
                  </td>
                  {seriesYears.map((year) => {
                    const rowsInYear = dimensionRows.filter((row) => row.year === year);
                    const row = pickAnnualSeriesRow(rowsInYear.filter((candidate) => candidate.item_name === item.name), seriesMetric);
                    const value = annualMetricValue(row, seriesMetric, rowsInYear);
                    return (
                      <td className={`numeric ${seriesMetric === "revenue_yoy_pct" && value != null && value < 0 ? "negative" : ""}`} key={year}>
                        {formatAnnualMetric(value, seriesMetric)}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {viewMode === "snapshot" && visibleRows.length ? (
        <>
          <div className="annual-bars">
            {visibleRows.slice(0, 12).map((row) => {
              const share = disclosureShare(row, visibleRows);
              return (
                <div className="annual-bar-row" key={`${row.year}-${row.dimension}-${row.item_name}-${row.source_line}`}>
                  <div className="annual-bar-label" title={row.item_name}>{row.item_name}</div>
                  <div className="annual-bar-track">
                    <span style={{ width: `${Math.max(2, Math.min(100, share ?? 0))}%` }} />
                  </div>
                  <div className="annual-bar-value">{share == null ? "-" : formatPctPoint(share, 1)}</div>
                  <div className="annual-bar-revenue">{formatYuan(row.revenue_yuan)}</div>
                </div>
              );
            })}
          </div>

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
                  <th>置信度</th>
                </tr>
              </thead>
              <tbody>
                {visibleRows.map((row) => {
                  const share = disclosureShare(row, visibleRows);
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
                        <small className="source-line">line {row.source_line}</small>
                      </td>
                      <td>
                        <span className={`confidence-pill ${row.confidence}`}>{row.confidence || "-"}</span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      ) : null}

      {(viewMode === "snapshot" && !visibleRows.length) || (viewMode === "series" && !seriesItems.length) ? (
        <div className="annual-empty">
          <h3>当前维度无披露项</h3>
          <p>这一年报没有抽到该维度下的收入拆分。</p>
        </div>
      ) : null}
    </section>
  );
}

function YamlWorkbook({
  companyId,
  initialPresentation,
  revenueView,
  statementSheets,
  fullStatementSheets,
  stashView,
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
      const result = await generateAssumptionBrief(companyId, patches, preview?.dcf_summary ?? null);
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

  // 三区一轴：每区一张表、一个共享年份轴，缺数据留空。约定分派，非公司特判。
  const allStash = stashView ?? [];
  const secondaryBlocks = allStash.filter((b) => b.name.includes("拆分"));
  const refBlocks = allStash.filter((b) => !b.name.includes("拆分"));

  // ① 收入拆分区
  const revenueBase = revenueView ? Number(revenueView.base_year) : 0;
  const revenueYears = revenueView
    ? unionYears([
        ...revenueView.segments.map((s) => Object.keys(s.history_revenues ?? {})),
        revenueView.years,
        ...secondaryBlocks.map((b) => b.items.filter(isSeriesItem).flatMap((it) => Object.keys(it.values))),
        [String(revenueView.base_year)],
      ])
    : [];
  const revenueGroups = revenueView ? buildRevenueGroups(revenueView, presentation, secondaryBlocks, editableRows, fullStatementSheets, preview?.statement_sheets) : [];

  // ② 关键假设区
  const asmBase = assumptionsView ? Number(assumptionsView.base_period) : 0;
  const assumptionGroups = assumptionsView ? buildAssumptionsGroups(assumptionsView) : [];
  const assumptionYears = assumptionsView?.years ?? [];
  const terminal = assumptionsView?.terminal;
  const representedEditablePaths = new Set<string>();
  for (const group of [...revenueGroups, ...assumptionGroups]) {
    for (const row of group.rows) {
      if (row.editablePath) representedEditablePaths.add(row.editablePath);
    }
  }
  const nonInlineEditableRows = revenueView ? editableRows.filter((row) => row.group !== "revenue_driver") : editableRows;
  const supplementalEditableRows = nonInlineEditableRows;
  const supplementalEditableGroups = buildEditableAxisGroups(supplementalEditableRows, representedEditablePaths);
  const modelGroups = [...revenueGroups, ...supplementalEditableGroups, ...assumptionGroups];
  const modelYears = unionYears([revenueYears, assumptionYears, editablePeriodList]);

  // ③ 参考区
  const refBase = revenueBase || asmBase;
  const { groups: refGroups, rest: refRest } = buildReferenceGroups(refBlocks);
  const refYears = unionYears(refGroups.map((g) => g.rows.flatMap((r) => Object.keys(r.values))));
  const revenueLastYear = revenueView?.years.length ? revenueView.years[revenueView.years.length - 1] : null;
  const overrideCount = editableRows.length;
  const yamlHeroStats = [
    { label: "BASE", value: String(revenueBase || asmBase || "-") },
    { label: "FORECAST", value: revenueView?.years.length ? `${revenueView.years[0]}-${revenueLastYear}` : "-" },
    { label: "SEGMENTS", value: String(revenueView?.segments.length ?? 0) },
    { label: "EDITABLE", value: String(overrideCount) },
  ];

  return (
    <div className="view-stack yaml1-spec">
      <section className="hero-block yaml-hero-card">
        <div className="yaml-hero-copy">
          <div className="eyebrow">YAML1 · 模型说明书</div>
          <h1>{presentation?.title || "收入拆分 + 关键假设 + 参考项"}</h1>
          <div className="hero-meta">
            <span>{path ?? "yaml1_*.yaml"}</span>
          </div>
          {presentation?.subtitle ? <p className="hero-subtitle">{presentation.subtitle}</p> : null}
        </div>
        <div className="yaml-hero-side">
          <div className="yaml-hero-stats">
            {yamlHeroStats.map((item) => (
              <div key={item.label}>
                <span>{item.label}</span>
                <strong>{item.value}</strong>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="card yaml-region assumption-workbench-toolbar">
        <div className="yaml-region-heading">
          <div>
            <div className="eyebrow">Model edit mode</div>
            <h2>假设试算工作台</h2>
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
              {briefLoading ? "生成中..." : "生成 /ka prompt"}
            </button>
          </div>
        </div>
        <div className="assumption-preview-status">
          <span>{patches.length ? `${patches.length} 处改动` : "无草稿改动"}</span>
          <span>{previewLoading ? "Preview 重算中..." : preview ? "Preview 已更新" : "使用正式 forecast"}</span>
          {preview?.dcf_summary?.per_share_value != null ? <strong>试算每股 {formatNumber(preview.dcf_summary.per_share_value, 2)}</strong> : null}
        </div>
        {previewError ? <div className="error-banner">{previewError}</div> : null}
        {briefError ? <div className="error-banner">{briefError}</div> : null}
        {briefPrompt ? (
          <div className="ka-prompt-box">
            <div className="eyebrow">KA prompt</div>
            <textarea readOnly value={briefPrompt} />
          </div>
        ) : null}
      </section>

      {modelGroups.length > 0 ? (
        <section className="card yaml-region">
          <div className="yaml-region-heading">
            <div className="eyebrow">① Model table</div>
            <h2>收入拆分 + 关键假设</h2>
          </div>
          <UnifiedYearTable
            years={modelYears}
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

      {nonInlineEditableRows.length > 0 ? (
        <details className="card yaml-region assumption-advanced-list">
          <summary>
            <span>全部可调假设</span>
            <small>{nonInlineEditableRows.length} knobs</small>
          </summary>
          <EditableAssumptionsTable editable={nonInlineEditableRows} editMode={editMode} drafts={draftValues} onDraft={updateDraft} />
        </details>
      ) : null}

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
          <section className="presentation-notes business-read-notes">
            {insightItems.length ? (
              <div className="business-read">
                <div className="eyebrow">Business read</div>
                <ul>{insightItems.map((item) => <li key={item}>{item}</li>)}</ul>
              </div>
            ) : null}
            {riskItems.length ? (
              <aside className="risk-footnote">
                <div className="eyebrow">Things to review</div>
                <ul>{riskItems.map((item) => <li key={item}>{item}</li>)}</ul>
              </aside>
            ) : null}
          </section>
        ) : null}
      </section>

      {(refGroups.length > 0 || refRest.length > 0) ? (
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
                <StashBlockView block={b} key={i} />
              ))}
            </div>
          ) : null}
        </section>
      ) : null}

      <AnnualRevenueDisclosure rows={annualRevenueBreakdown} modelSegments={revenueView?.segments ?? []} />

      {yaml1Text ? (
        <details className="raw-yaml-block">
          <summary>
            <span>原始 YAML1</span>
            <small>{path ?? ""}</small>
          </summary>
          <pre className="raw-yaml-pre">{yaml1Text}</pre>
        </details>
      ) : null}
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
    setValues(initial);
  }, [initial.wacc, initial.terminalGrowth, initial.terminalCapexDaRatio]);

  useEffect(() => {
    const timer = setTimeout(() => onChange(values), 300);
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
          <FullStatementTable basePeriod={basePeriod} sheet={activeSheet} showTechnicalRows={showTechnicalRows} showZeroRows={showZeroRows} years={visibleYears} />
        ) : null}
      </div>
    </div>
  );
}

function DcfView({ detail }: { detail: CompanyDetail }) {
  const [dcf, setDcf] = useState(detail.dcf_summary);
  const [sensitivityLoading, setSensitivityLoading] = useState(false);
  const [sensitivityError, setSensitivityError] = useState<string | null>(null);

  useEffect(() => {
    setDcf(detail.dcf_summary);
  }, [detail.dcf_summary]);

  async function handleSensitivityChange(state: SensitivityState) {
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

  const initialSensitivity: SensitivityState = {
    wacc: Number(detail.dcf_summary?.wacc ?? 0.08),
    terminalGrowth: Number(detail.dcf_summary?.terminal_growth ?? 0.025),
    terminalCapexDaRatio: Number(detail.dcf_summary?.terminal_capex_da_ratio ?? 1.0),
  };

  return (
    <div className="view-stack">
      <div className="dcf-topline">
        <section className="metric-grid dcf-metric-grid">
          <MetricCard label="Per-share value" value={formatNumber(dcf?.per_share_value)} caption="DCF 输出" />
          <MetricCard label="Enterprise value" value={formatNumber(dcf?.enterprise_value)} />
          <MetricCard label="Equity value" value={formatNumber(dcf?.equity_value)} />
          <MetricCard label="Terminal PV" value={formatNumber(dcf?.terminal_pv)} />
        </section>
        <SensitivityPanel
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

function MaterialsView({ files }: { files: FileItem[] }) {
  if (!files.length) {
    return <EmptyState title="No material index" body="active_vore/ and extractions/ are empty or missing for this company." />;
  }
  return (
    <section className="card">
      <div className="section-heading">
        <div>
          <div className="eyebrow">Source material</div>
          <h2>active_vore and extraction files</h2>
        </div>
      </div>
      <div className="file-list">
        {files.map((file) => (
          <div className="file-row" key={file.path}>
            <div>
              <div className="file-name">{file.name}</div>
              <div className="file-path">{file.path}</div>
            </div>
            <div className="file-meta">
              <span>{file.kind.toUpperCase()}</span>
              <span>{formatNumber(file.size / 1024, 1)} KB</span>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
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
  running,
  onRun,
}: {
  detail: CompanyDetail;
  tab: TabKey;
  running: boolean;
  onRun: () => void;
}) {
  if (tab === "overview") return <Overview detail={detail} running={running} onRun={onRun} />;
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
        assumptionsView={detail.yaml1_assumptions_view}
        editableAssumptions={detail.editable_assumptions}
        annualRevenueBreakdown={detail.annual_revenue_breakdown}
        yaml1Text={detail.yaml1_text}
      />
    );
  }
  if (tab === "dcf") return <DcfView detail={detail} />;
  return <MaterialsView files={detail.materials} />;
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

  async function loadCompanies() {
    setLoading(true);
    setError(undefined);
    try {
      const result = await apiGet<CompanySummary[]>("/api/companies");
      setCompanies(result);
      setSelectedId((current) => current ?? result[0]?.id);
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
  }, []);

  useEffect(() => {
    if (selectedId) void loadDetail(selectedId);
  }, [selectedId]);

  const selectedCompany = companies.find((company) => company.id === selectedId);
  const headerStats = selectedCompany
    ? [
        ["VALUE", formatNumber(statValue(selectedCompany, "per_share_value"))],
        ["BASE", selectedCompany.base_period ?? "-"],
        ["UPDATED", formatDate(selectedCompany.updated_at)],
      ]
    : [];

  return (
    <div className="app-shell">
      <Sidebar companies={companies} loading={loading} onSelect={setSelectedId} selectedId={selectedId} />
      <main className="main-pane">
        <header className="topbar">
          <div>
            <div className="eyebrow">Workbench</div>
            <h1>{selectedCompany?.name ?? "Company folder"}</h1>
          </div>
          <div className="topbar-stats">
            {headerStats.map(([label, value]) => (
              <div className="topbar-stat" key={label}>
                <span>{label}</span>
                <strong>{value}</strong>
              </div>
            ))}
          </div>
        </header>

        <nav className="tabbar">
          {tabs.map((item) => (
            <button className={tab === item.key ? "active" : ""} key={item.key} onClick={() => setTab(item.key)} type="button">
              {item.label}
            </button>
          ))}
        </nav>

        {error ? <div className="error-banner">{error}</div> : null}
        {detailLoading ? <div className="activity content-activity">Loading company model</div> : null}
        {!detailLoading && detail ? <DetailView detail={detail} onRun={regenerateForecast} running={running} tab={tab} /> : null}
        {!detailLoading && !detail && !error ? <EmptyState title="No company selected" body="Select a company from the sidebar to inspect its model folder." /> : null}
      </main>
    </div>
  );
}
