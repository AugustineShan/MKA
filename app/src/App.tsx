import { useEffect, useMemo, useState } from "react";
import type {
  CompanyDetail,
  CompanySummary,
  FileItem,
  StatementSheet,
  TabKey,
  TableFile,
  WorkbookSheet,
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

function RevenueAssumptions({ view }: { view: Yaml1RevenueView }) {
  const columns = [String(view.base_year), ...view.years];
  return (
    <div className="revenue-assumptions">
      <section className="assumption-hero">
        <div>
          <div className="eyebrow">YAML1 Revenue Assumptions</div>
          <h2>收入拆分与增长路径</h2>
          <p>由 YAML1 的 decomposition 确定性展开。金额单位：百万元；增长率为同比。</p>
        </div>
        <div className="assumption-summary">
          <span>{view.base_year}A</span>
          <strong>{formatNumber(view.base_revenue)}</strong>
        </div>
      </section>

      <section className="spreadsheet-card">
        <div className="section-heading compact">
          <div>
            <div className="eyebrow">Total revenue bridge</div>
            <h2>总收入路径</h2>
          </div>
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
                    {formatPercent(view.yoy[year])}
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section className="spreadsheet-card">
        <div className="section-heading compact">
          <div>
            <div className="eyebrow">Business line build</div>
            <h2>四条业务线收入</h2>
          </div>
        </div>
        <div className="table-scroll workbook-scroll">
          <table className="financial-table assumption-table">
            <thead>
              <tr>
                <th>业务线</th>
                <th>族</th>
                <th className="numeric">{view.base_year}A</th>
                <th className="numeric">基准量</th>
                <th className="numeric">基准价</th>
                {view.years.map((year) => (
                  <th className="numeric" key={year}>
                    {year}E
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {view.segments.map((segment) => (
                <tr key={segment.key}>
                  <td className="statement-label" title={segment.note ?? segment.name}>
                    <span>{segment.name}</span>
                  </td>
                  <td>{segment.family === "vol_price" ? "量价" : "增速"}</td>
                  <td className="numeric">{formatNumber(segment.base_revenue)}</td>
                  <td className="numeric">{segment.base_volume == null ? "-" : formatNumber(segment.base_volume)}</td>
                  <td className="numeric">{segment.base_price == null ? "-" : formatNumber(segment.base_price)}</td>
                  {view.years.map((year) => (
                    <td className="numeric" key={year}>
                      {formatNumber(segment.revenues[year])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="spreadsheet-card">
        <div className="section-heading compact">
          <div>
            <div className="eyebrow">Drivers</div>
            <h2>分年驱动假设</h2>
          </div>
        </div>
        <div className="table-scroll workbook-scroll">
          <table className="financial-table assumption-table">
            <thead>
              <tr>
                <th>业务线</th>
                <th>驱动</th>
                {view.years.map((year) => (
                  <th className="numeric" key={year}>
                    {year}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {view.drivers.map((driver) => (
                <tr key={`${driver.segment}-${driver.driver}`}>
                  <td>{driver.segment}</td>
                  <td>{driver.driver}</td>
                  {view.years.map((year) => (
                    <td className={`numeric ${driver.values[year] < 0 ? "negative" : ""}`} key={year}>
                      {formatPercent(driver.values[year])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function YamlWorkbook({ revenueView, sheets, path }: { revenueView?: Yaml1RevenueView | null; sheets?: WorkbookSheet[]; path?: string | null }) {
  const available = sheets ?? [];
  const defaultSheet = revenueView ? "Revenue Assumptions" : available[0]?.name ?? "";
  const [active, setActive] = useState(defaultSheet);
  const sheet = available.find((item) => item.name === active) ?? available[0];
  const auxiliary = [
    { key: "Revenue Assumptions", label: "Revenue Assumptions", count: revenueView?.segments.length },
    ...available.map((item) => ({ key: item.name, label: item.name, count: item.rows.length })),
  ].filter((item) => item.key !== "Revenue Assumptions" || revenueView);

  useEffect(() => {
    setActive(defaultSheet);
  }, [defaultSheet, path]);

  if (!revenueView && !sheet) {
    return <EmptyState title="No YAML1 workbook" body="Compiler output yaml1_*.yaml was not found or could not be parsed." />;
  }

  return (
    <div className="workbook-shell">
      <div className="workbook-header">
        <div>
          <div className="eyebrow">YAML1 workbook</div>
          <h2>Analyst assumptions</h2>
          <p>{path ?? "yaml1_*.yaml"}</p>
        </div>
        <StatusPill label={revenueView ? "Revenue first" : `${available.length} sheets`} />
      </div>
      <SheetTabs active={active} items={auxiliary} onSelect={setActive} />
      {active === "Revenue Assumptions" && revenueView ? (
        <RevenueAssumptions view={revenueView} />
      ) : sheet ? (
        <SpreadsheetTable columns={sheet.columns} description={sheet.description} rows={sheet.rows} title={sheet.name} />
      ) : null}
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

function DcfView({ detail }: { detail: CompanyDetail }) {
  const dcf = detail.dcf_summary;
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

  return (
    <div className="view-stack">
      <section className="metric-grid">
        <MetricCard label="Enterprise value" value={formatNumber(dcf?.enterprise_value)} />
        <MetricCard label="Equity value" value={formatNumber(dcf?.equity_value)} />
        <MetricCard label="PV FCFF" value={formatNumber(dcf?.pv_fcff)} />
        <MetricCard label="Terminal PV" value={formatNumber(dcf?.terminal_pv)} />
      </section>
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
    return <YamlWorkbook path={detail.yaml1_path} revenueView={detail.yaml1_revenue_view} sheets={detail.yaml1_sheets} />;
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
