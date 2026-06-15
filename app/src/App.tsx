import { Fragment, useEffect, useMemo, useState } from "react";
import type {
  CompanyDetail,
  CompanySummary,
  FileItem,
  StatementSheet,
  TabKey,
  TableFile,
  WorkbookSheet,
  Yaml1Presentation,
  Yaml1RevenueView,
} from "./types";

const tabs: Array<{ key: TabKey; label: string }> = [
  { key: "overview", label: "Overview" },
  { key: "assumptions", label: "Core Assumption" },
  { key: "yaml1", label: "YAML1" },
  { key: "dcf", label: "DCF" },
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

function sheetLabel(name: string): string {
  const labels: Record<string, string> = {
    Meta: "模型信息",
    "Revenue Build": "收入底稿",
    "DCF Knobs": "估值参数",
    Stash: "历史观测",
  };
  return labels[name] ?? name;
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

function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let inQuotes = false;

  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    const next = text[i + 1];
    if (char === '"' && inQuotes && next === '"') {
      cell += '"';
      i += 1;
    } else if (char === '"') {
      inQuotes = !inQuotes;
    } else if (char === "," && !inQuotes) {
      row.push(cell);
      cell = "";
    } else if ((char === "\n" || char === "\r") && !inQuotes) {
      if (char === "\r" && next === "\n") i += 1;
      row.push(cell);
      if (row.some((item) => item !== "")) rows.push(row);
      row = [];
      cell = "";
    } else {
      cell += char;
    }
  }
  if (cell || row.length) {
    row.push(cell);
    rows.push(row);
  }
  return rows;
}

function isNumericCell(value: string): boolean {
  if (!value.trim()) return false;
  return !Number.isNaN(Number(value.replace(/,/g, "")));
}

function formatHeader(value: string): string {
  return value.replace(/_/g, " ").toUpperCase();
}

function formatTableCell(value: unknown, column: string): string {
  const text = String(value ?? "");
  if (!text.trim()) return "";
  if (column.toLowerCase() === "period") return String(Math.round(Number(text)));
  if (isNumericCell(text)) return formatNumber(Number(text.replace(/,/g, "")));
  return text;
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

function MarkdownView({ text }: { text?: string | null }) {
  if (!text) {
    return <EmptyState title="No core assumption file" body="This company folder does not contain a core assumption markdown file yet." />;
  }
  const blocks = text.split(/\n{2,}/);
  return (
    <div className="markdown-card">
      {blocks.map((block, index) => {
        const trimmed = block.trim();
        if (!trimmed) return null;
        if (trimmed.startsWith("### ")) return <h3 key={index}>{trimmed.slice(4)}</h3>;
        if (trimmed.startsWith("## ")) return <h2 key={index}>{trimmed.slice(3)}</h2>;
        if (trimmed.startsWith("# ")) return <h1 key={index}>{trimmed.slice(2)}</h1>;
        if (trimmed.startsWith("- ")) {
          return (
            <ul key={index}>
              {trimmed.split("\n").map((line) => (
                <li key={line}>{line.replace(/^- /, "")}</li>
              ))}
            </ul>
          );
        }
        return <p key={index}>{trimmed}</p>;
      })}
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

function SpreadsheetTable({
  title,
  description,
  path,
  columns,
  rows,
}: {
  title: string;
  description?: string | null;
  path?: string | null;
  columns: string[];
  rows: Array<Record<string, unknown>>;
}) {
  return (
    <section className="spreadsheet-card">
      <div className="section-heading compact">
        <div>
          <div className="eyebrow">{description ?? "Workbook sheet"}</div>
          <h2>{title}</h2>
        </div>
        {path ? <div className="table-path">{path}</div> : null}
      </div>
      <div className="table-scroll workbook-scroll">
        <table className="financial-table workbook-table">
          <thead>
            <tr>
              {columns.map((column) => (
                <th key={column}>{formatHeader(column)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, rowIndex) => (
              <tr key={`${title}-${rowIndex}`}>
                {columns.map((column, columnIndex) => {
                  const raw = row[column];
                  const text = String(raw ?? "");
                  const numeric = isNumericCell(text) && column.toLowerCase() !== "period";
                  const value = Number(text.replace(/,/g, ""));
                  return (
                    <td className={numeric ? `numeric ${value < 0 ? "negative" : ""}` : ""} key={`${column}-${columnIndex}`} title={text}>
                      {formatTableCell(raw, column)}
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
            <h2>业务线拆分</h2>
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

function YamlWorkbook({
  companyId,
  initialPresentation,
  revenueView,
  sheets,
  statementSheets,
  path,
}: {
  companyId: string;
  initialPresentation?: Yaml1Presentation | null;
  revenueView?: Yaml1RevenueView | null;
  sheets?: WorkbookSheet[];
  statementSheets?: StatementSheet[];
  path?: string | null;
}) {
  const available = sheets ?? [];
  const defaultSheet = available[0]?.name ?? "";
  const [active, setActive] = useState(defaultSheet);
  const [presentation, setPresentation] = useState<Yaml1Presentation | null>(initialPresentation ?? null);
  const [presentationStatus, setPresentationStatus] = useState<string[]>([]);
  const [presentationError, setPresentationError] = useState<string | null>(null);
  const [presentationRunning, setPresentationRunning] = useState(false);
  const [businessPage, setBusinessPage] = useState<"summary" | "detail">("summary");
  const sheet = available.find((item) => item.name === active) ?? available[0];
  const auxiliary = available.map((item) => ({ key: item.name, label: sheetLabel(item.name), count: item.rows.length }));

  useEffect(() => {
    setActive(defaultSheet);
    setPresentation(initialPresentation ?? null);
    setPresentationStatus([]);
    setPresentationError(null);
    setPresentationRunning(false);
    setBusinessPage("summary");
  }, [defaultSheet, initialPresentation, path]);

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

  if (!revenueView && !sheet) {
    return <EmptyState title="No YAML1 workbook" body="Compiler output yaml1_*.yaml was not found or could not be parsed." />;
  }

  if (revenueView) {
    return (
      <div className="workbook-shell business-workbook">
        <section className="business-pagebar">
          <div className="business-switcher" aria-label="YAML1 business sections">
            {[
              ["summary", "结论"],
              ["detail", "经营明细"],
            ].map(([key, label]) => (
              <button className={businessPage === key ? "active" : ""} key={key} onClick={() => setBusinessPage(key as "summary" | "detail")} type="button">
                {label}
              </button>
            ))}
          </div>
          <button disabled={presentationRunning} onClick={generatePresentation} type="button">
            {presentationRunning ? "生成中..." : presentation ? "重新生成" : "生成业务展示"}
          </button>
        </section>
        {presentationStatus.length || presentationError ? (
          <section className="ai-stream">
            {presentationStatus.map((item, index) => (
              <div className={index === presentationStatus.length - 1 && presentationRunning ? "active" : ""} key={`${item}-${index}`}>
                {item}
              </div>
            ))}
            {presentationError ? <div className="error">{presentationError}</div> : null}
          </section>
        ) : null}
        <RevenueAssumptions page={businessPage} presentation={presentation} statementSheets={statementSheets} view={revenueView} />
      </div>
    );
  }

  return (
    <div className="workbook-shell">
      <div className="workbook-header">
        <div>
          <div className="eyebrow">YAML1 workbook</div>
          <h2>业务假设</h2>
          <p>{path ?? "yaml1_*.yaml"}</p>
        </div>
        <StatusPill label={`${available.length} sheets`} />
      </div>
      <SheetTabs active={active} items={auxiliary} onSelect={setActive} />
      {sheet ? <SpreadsheetTable columns={sheet.columns} description={sheet.description} rows={sheet.rows} title={sheetLabel(sheet.name)} /> : null}
    </div>
  );
}

function FinancialTable({ table }: { table: TableFile }) {
  const rows = useMemo(() => parseCsv(table.csv), [table.csv]);
  const headers = rows[0] ?? [];
  const body = rows.slice(1, 100).map((row) => Object.fromEntries(headers.map((header, index) => [header, row[index] ?? ""])));
  return <SpreadsheetTable columns={headers} description="Financial statement" path={table.path} rows={body} title={table.name} />;
}

function StatementTable({ sheet, showZeroRows }: { sheet: StatementSheet; showZeroRows: boolean }) {
  const rows = sheet.rows.filter((row) => showZeroRows || !row.is_zero || row.role !== "normal");
  return (
    <section className="spreadsheet-card statement-card">
      <div className="section-heading compact">
        <div>
          <div className="eyebrow">{sheet.unit}</div>
          <h2>{sheet.title}</h2>
        </div>
        <div className="table-path">{sheet.path}</div>
      </div>
      <div className="table-scroll workbook-scroll">
        <table className="financial-table statement-table">
          <thead>
            <tr>
              <th>科目</th>
              {sheet.years.map((year) => (
                <th className="numeric" key={year}>
                  {year}
                </th>
              ))}
              <th>字段</th>
              <th>分类</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr className={`${row.role} level-${row.level}`} key={row.field}>
                <td className="statement-label" title={`${row.label} (${row.field})`}>
                  <span>{row.label}</span>
                </td>
                {sheet.years.map((year) => {
                  const value = row.values[year];
                  return (
                    <td className={`numeric ${typeof value === "number" && value < 0 ? "negative" : ""}`} key={`${row.field}-${year}`}>
                      {typeof value === "number" ? formatNumber(value) : ""}
                    </td>
                  );
                })}
                <td className="statement-field">{row.field}</td>
                <td>{row.category_label}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
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
}: {
  initial: SensitivityState;
  onChange: (state: SensitivityState) => void;
  loading: boolean;
  error?: string | null;
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
    <section className="card sensitivity-card">
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

function DcfView({ detail }: { detail: CompanyDetail }) {
  const [dcf, setDcf] = useState(detail.dcf_summary);
  const [sensitivityLoading, setSensitivityLoading] = useState(false);
  const [sensitivityError, setSensitivityError] = useState<string | null>(null);
  const sheets = detail.statement_sheets ?? [];
  const [active, setActive] = useState(sheets[0]?.key ?? "is");
  const [showZeroRows, setShowZeroRows] = useState(false);
  const activeSheet = sheets.find((sheet) => sheet.key === active) ?? sheets[0];
  const ordered = [
    { key: "forecast_is.csv", label: "IS" },
    { key: "forecast_bs.csv", label: "BS" },
    { key: "forecast_cf.csv", label: "CF" },
  ];
  const fallbackTables = ordered
    .map((item) => ({ ...item, table: detail.tables.find((table) => table.name === item.key) }))
    .filter((item): item is { key: string; label: string; table: TableFile } => Boolean(item.table));
  const activeFallbackTable = fallbackTables.find((item) => item.key === active)?.table ?? fallbackTables[0]?.table;

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
      <section className="metric-grid">
        <MetricCard label="Per-share value" value={formatNumber(dcf?.per_share_value)} />
        <MetricCard label="Enterprise value" value={formatNumber(dcf?.enterprise_value)} />
        <MetricCard label="Equity value" value={formatNumber(dcf?.equity_value)} />
        <MetricCard label="Terminal PV" value={formatNumber(dcf?.terminal_pv)} />
      </section>
      <SensitivityPanel
        error={sensitivityError}
        initial={initialSensitivity}
        loading={sensitivityLoading}
        onChange={handleSensitivityChange}
      />
      {activeSheet ? (
        <div className="workbook-shell">
          <div className="workbook-header">
            <div>
              <div className="eyebrow">Forecast workbook</div>
              <h2>Income Statement / Balance Sheet / Cash Flow</h2>
            </div>
            <label className="zero-toggle">
              <input checked={showZeroRows} onChange={(event) => setShowZeroRows(event.currentTarget.checked)} type="checkbox" />
              Show zero rows
            </label>
          </div>
          <SheetTabs active={activeSheet.key} items={sheets.map((sheet) => ({ key: sheet.key, label: sheet.name, count: sheet.rows.length }))} onSelect={setActive} />
          <StatementTable sheet={activeSheet} showZeroRows={showZeroRows} />
        </div>
      ) : activeFallbackTable ? (
        <div className="workbook-shell">
          <div className="workbook-header">
            <div>
              <div className="eyebrow">Forecast workbook</div>
              <h2>Raw CSV fallback</h2>
            </div>
            <StatusPill label="forecast/" />
          </div>
          <SheetTabs active={activeFallbackTable.name} items={fallbackTables.map((item) => ({ key: item.key, label: item.label }))} onSelect={setActive} />
          <FinancialTable table={activeFallbackTable} />
        </div>
      ) : (
        <EmptyState title="No forecast tables" body="Run the DCF model to generate forecast/ outputs." />
      )}
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
  if (tab === "assumptions") return <MarkdownView text={detail.core_assumption_md} />;
  if (tab === "yaml1") {
    return (
      <YamlWorkbook
        companyId={detail.summary.id}
        initialPresentation={detail.yaml1_presentation}
        path={detail.yaml1_path}
        revenueView={detail.yaml1_revenue_view}
        sheets={detail.yaml1_sheets}
        statementSheets={detail.statement_sheets}
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
