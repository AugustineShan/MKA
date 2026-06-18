import { Fragment, useEffect, useMemo, useState } from "react";
import type {
  AssumptionsKnob,
  AssumptionsSection,
  CompanyDetail,
  CompanySummary,
  DcfDetailRow,
  FileItem,
  StashBlock,
  StatementSheet,
  TabKey,
  TerminalView,
  TraceabilityItem,
  Yaml1AssumptionsView,
  Yaml1Presentation,
  Yaml1RevenueView,
} from "./types";

const tabs: Array<{ key: TabKey; label: string }> = [
  { key: "overview", label: "Overview" },
  { key: "yaml1", label: "核心假设展示" },
  { key: "statements", label: "完整三表" },
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

// ─────────────────────────── Assumptions panel ───────────────────────────

function KnobRow({ knob, years }: { knob: AssumptionsKnob; years: string[] }) {
  const label = knob.src.replace(/^#/, "").replace(/\(.*\)$/, "").trim() || knob.path;
  return (
    <tr className={knob.is_override ? "override-row" : ""}>
      <td className="statement-label" title={`${knob.path}${knob.note ? " · " + knob.note : ""}`}>
        {knob.is_override ? <span className="override-dot" title="主动覆盖 / 查证" /> : null}
        {label}
      </td>
      {years.map((y, i) => {
        const v = knob.values[i];
        const isRate = knob.path.includes("gpm") || knob.path.includes("cost_rates") || knob.path.includes("tax_rate") || knob.path.includes("minority");
        return (
          <td className={`numeric ${typeof v === "number" && v < 0 ? "negative" : ""}`} key={y}>
            {typeof v === "number" ? (isRate ? formatPercent(v, 2) : formatNumber(v)) : "-"}
          </td>
        );
      })}
    </tr>
  );
}

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

function AssumptionsPanel({ view }: { view: Yaml1AssumptionsView | null | undefined }) {
  if (!view) return <EmptyState title="无假设旋钮" body="这份 yaml1 没有结构化假设视图。" />;
  const base = Number(view.base_period);
  const yearLabel = (y: string) => (Number(y) > base ? `${y}E` : y);
  return (
    <section className="card assumptions-panel">
      <div className="section-heading">
        <div>
          <div className="eyebrow">② Key assumptions · knobs</div>
          <h2>关键假设</h2>
          <p>老板拍板的旋钮：毛利率、费用率、营业利润调节项、税率、少数股东。蓝点 = 主动覆盖/查证。缺失 = 落 yaml2 平推。</p>
        </div>
        <StatusPill label={`${view.years.join(" · ")}`} />
      </div>
      <div className="assumptions-sections">
        {view.sections.map((sec: AssumptionsSection) => (
          <div className="assumptions-section" key={sec.key}>
            <h3>{sec.title}</h3>
            <div className="table-scroll workbook-scroll">
              <table className="financial-table assumption-table">
                <thead>
                  <tr className="year-header-row">
                    <th>科目</th>
                    {view.years.map((y) => <th className="numeric" key={y}>{yearLabel(y)}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {sec.knobs.map((k) => <KnobRow key={k.path} knob={k} years={view.years} />)}
                </tbody>
              </table>
            </div>
          </div>
        ))}
        <TerminalBlock terminal={view.terminal} />
        {view.traceability.length > 0 ? (
          <details className="traceability-block">
            <summary>
              <span>溯源附注</span>
              <small>{view.traceability.length}</small>
            </summary>
            <div className="stash-text-dict">
              {view.traceability.map((t: TraceabilityItem, i) => (
                <div className="stash-text-row" key={i}>
                  <span className="stash-text-label">{t.name}</span>
                  <span className="stash-text-body">{t.text}</span>
                </div>
              ))}
            </div>
          </details>
        ) : null}
      </div>
    </section>
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
  const terminalShare = ev && terminalPv ? Math.round((terminalPv / ev) * 100) : null;
  const highTerminal = terminalShare != null && terminalShare >= 60;
  if (perShare == null) return null;
  return (
    <section className="card valuation-bridge-card">
      <div className="section-heading">
        <div>
          <div className="eyebrow">How 17.03 is built</div>
          <h2>估值桥</h2>
        </div>
        {terminalShare != null ? (
          <span className={`terminal-share-warning ${highTerminal ? "warn" : ""}`}>终值占比 {terminalShare}%{highTerminal ? " · 估值高度依赖永续" : ""}</span>
        ) : null}
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

const IS_KEY_ROWS = new Set(["revenue", "oper_cost", "operate_profit", "total_profit", "n_income", "n_income_attr_p"]);

function FullStatementTable({ sheet, basePeriod, showZeroRows, years }: { sheet: StatementSheet; basePeriod: string; showZeroRows: boolean; years?: string[] }) {
  const visibleYears = years ?? sheet.years;
  const historyYears = useMemo(() => {
    const base = Number(basePeriod);
    return new Set(visibleYears.filter((y) => (Number(y) || 0) <= base));
  }, [visibleYears, basePeriod]);
  const rows = sheet.rows.filter((row) => showZeroRows || !row.is_zero || row.role !== "normal");
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
              <tr className={`${row.role} level-${row.level} ${IS_KEY_ROWS.has(row.field) ? "key-row" : ""}`} key={row.field}>
                <td className="statement-label" title={`${row.label} (${row.field})`}><span>{row.label}</span></td>
                {visibleYears.map((year) => {
                  const value = row.values[year];
                  return (
                    <td className={`numeric ${historyYears.has(year) ? "history-year" : "forecast-year"} ${typeof value === "number" && value < 0 ? "negative" : ""}`} key={`${row.field}-${year}`}>
                      {typeof value === "number" ? formatNumber(value) : ""}
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
  // int=整数金额(百万元) · num2=2位小数(参考项通用) · decimal=小数比率×100+%(旋钮) ·
  // signedDecimal=带符号同比% · volume=1位小数(万吨)
  format?: "int" | "num2" | "decimal" | "signedDecimal" | "volume";
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

function UnifiedYearTable({ years, baseYear, groups }: { years: string[]; baseYear: number; groups: AxisGroup[] }) {
  return (
    <div className="table-scroll workbook-scroll">
      <table className="financial-table unified-table">
        <thead>
          <tr className="year-header-row">
            <th>项目</th>
            {years.map((y) => (
              <th className="numeric" key={y}>{yearLabel(y, baseYear)}</th>
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
                <tr key={ri} className={`${r.bold ? "key-row" : ""} ${r.muted ? "muted-row" : ""}`}>
                  <td className="statement-label" title={r.note ?? r.label}>
                    {r.override ? <span className="override-dot" title="主动覆盖 / 查证" /> : null}
                    {r.label}
                  </td>
                  {years.map((y) => {
                    const v = r.values[y];
                    return (
                      <td className={`numeric ${typeof v === "number" && v < 0 ? "negative" : ""}`} key={y}>
                        {formatAxisCell(v, r.format)}
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

function buildRevenueGroups(view: Yaml1RevenueView, presentation: Yaml1Presentation | null | undefined, secondaryBlocks: StashBlock[], fullStatementSheets?: StatementSheet[]): AxisGroup[] {
  const groups: AxisGroup[] = [];
  // 总收入：历史从完整 IS 表 revenue 补全，base+预测来自 revenueView，拼成完整时间轴
  const fullIs = fullStatementSheets?.find((s) => s.key === "is");
  const totalValues: Record<string, number | null> = {};
  if (fullIs) {
    for (const y of fullIs.years) {
      if (Number(y) <= view.base_year) totalValues[y] = statementValue(fullIs, ["revenue"], y);
    }
  }
  totalValues[String(view.base_year)] = view.base_revenue;
  for (const y of view.years) totalValues[y] = view.revenues[y] ?? null;
  const totalYoy: Record<string, number | null> = yoySeries(totalValues);
  groups.push({
    title: "总收入",
    unit: "百万元",
    rows: [
      { label: "营业收入", bold: true, values: totalValues, format: "int" },
      { label: "同比增长", muted: true, values: totalYoy, format: "signedDecimal" },
    ],
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
    const revValues: Record<string, number | null> = { ...(seg.history_revenues ?? {}), ...seg.revenues };
    segRows.push({ label: `${seg.name} · 收入`, values: revValues, note: seg.note, format: "int" });
    const yoyValues: Record<string, number | null> = { ...yoySeries(seg.history_revenues), ...seg.yoys };
    segRows.push({ label: `${seg.name} · 同比`, muted: true, values: yoyValues, format: "signedDecimal" });
    if (seg.history_volumes || seg.volumes) {
      const volValues: Record<string, number | null> = { ...(seg.history_volumes ?? {}), ...(seg.volumes ?? {}) };
      segRows.push({ label: `${seg.name} · 销量(万吨)`, muted: true, values: volValues, format: "volume" });
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
      return { label: knobLabel(k), values, note: k.note, override: k.is_override, bold: k.is_override, format: knobIsRate(k.path) ? "decimal" : "int" };
    }),
  }));
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

function YamlWorkbook({
  companyId,
  initialPresentation,
  revenueView,
  statementSheets,
  fullStatementSheets,
  stashView,
  assumptionsView,
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
  yaml1Text?: string | null;
  path?: string | null;
}) {
  const [presentation, setPresentation] = useState<Yaml1Presentation | null>(initialPresentation ?? null);
  const [presentationStatus, setPresentationStatus] = useState<string[]>([]);
  const [presentationError, setPresentationError] = useState<string | null>(null);
  const [presentationRunning, setPresentationRunning] = useState(false);

  useEffect(() => {
    setPresentation(initialPresentation ?? null);
    setPresentationStatus([]);
    setPresentationError(null);
    setPresentationRunning(false);
  }, [initialPresentation, path]);

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

  if (!revenueView && !assumptionsView && !stashView?.length) {
    return <EmptyState title="No YAML1" body="Compiler output yaml1_*.yaml was not found or could not be parsed." />;
  }

  const insightItems = presentation?.insights?.filter(Boolean) ?? [];
  const riskItems = presentation?.risks?.filter(Boolean) ?? [];

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
  const revenueGroups = revenueView ? buildRevenueGroups(revenueView, presentation, secondaryBlocks, fullStatementSheets) : [];

  // ② 关键假设区
  const asmBase = assumptionsView ? Number(assumptionsView.base_period) : 0;
  const asmYears = assumptionsView ? assumptionsView.years.filter((y) => isYearKeyStr(y)) : [];
  const asmGroups = assumptionsView ? buildAssumptionsGroups(assumptionsView) : [];
  const terminal = assumptionsView?.terminal;

  // ③ 参考区
  const refBase = revenueBase || asmBase;
  const { groups: refGroups, rest: refRest } = buildReferenceGroups(refBlocks);
  const refYears = unionYears(refGroups.map((g) => g.rows.flatMap((r) => Object.keys(r.values))));

  return (
    <div className="view-stack yaml1-spec">
      <section className="hero-block">
        <div>
          <div className="eyebrow">YAML1 · 模型说明书</div>
          <h1>{presentation?.title || "收入拆分 + 关键假设 + 参考项"}</h1>
          <div className="hero-meta">
            <span>{path ?? "yaml1_*.yaml"}</span>
          </div>
          {presentation?.subtitle ? <p className="hero-subtitle">{presentation.subtitle}</p> : null}
        </div>
        <button className="primary-button" disabled={presentationRunning} onClick={generatePresentation} type="button">
          {presentationRunning ? "生成中..." : presentation ? "重新生成业务解读" : "生成业务解读"}
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

      {insightItems.length || riskItems.length ? (
        <section className="presentation-notes">
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

      {revenueGroups.length > 0 ? (
        <section className="card yaml-region">
          <div className="yaml-region-heading">
            <div className="eyebrow">① Revenue breakdown</div>
            <h2>收入拆分</h2>
            <p>总收入 · 主拆分（业务线）· 副拆分（地域 / 子公司）共享同一时间轴；无数据留空。副拆分来自外部模型，不参与营收计算。</p>
          </div>
          <UnifiedYearTable years={revenueYears} baseYear={revenueBase} groups={revenueGroups} />
        </section>
      ) : null}

      {asmGroups.length > 0 ? (
        <section className="card yaml-region">
          <div className="yaml-region-heading">
            <div className="eyebrow">② Key assumptions · knobs</div>
            <h2>关键假设</h2>
            <p>毛利率 · 费用率 · 营业利润调节 · 税率少数股东，共享同一预测期时间轴。蓝点 = 主动覆盖 / 查证；缺失 = 落 yaml2 平推。</p>
          </div>
          <UnifiedYearTable years={asmYears} baseYear={asmBase} groups={asmGroups} />
          {terminal && terminal.explicit_end != null ? <TerminalBlock terminal={terminal} /> : null}
        </section>
      ) : null}

      {refGroups.length > 0 || refRest.length > 0 ? (
        <section className="card yaml-region">
          <div className="yaml-region-heading">
            <div className="eyebrow">③ Reference items · stash</div>
            <h2>参考项</h2>
            <p>历史观测 · 核对项共享同一时间轴；口径说明 / 溯源附注 / 定性情报见下方折叠。无删减，无数据留空。</p>
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

function StatementsView({ detail }: { detail: CompanyDetail }) {
  const sheets = detail.full_statement_sheets?.length ? detail.full_statement_sheets : detail.statement_sheets ?? [];
  const [active, setActive] = useState(sheets[0]?.key ?? "is");
  const [showZeroRows, setShowZeroRows] = useState(false);
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
              Show zero rows
            </label>
          </div>
        </div>
        <SheetTabs active={active} items={sheets.map((sheet) => ({ key: sheet.key, label: sheet.name, count: sheet.rows.length }))} onSelect={setActive} />
        {activeSheet ? (
          <FullStatementTable basePeriod={basePeriod} sheet={activeSheet} showZeroRows={showZeroRows} years={visibleYears} />
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
      <section className="metric-grid">
        <MetricCard label="Per-share value" value={formatNumber(dcf?.per_share_value)} caption="DCF 输出" />
        <MetricCard label="Enterprise value" value={formatNumber(dcf?.enterprise_value)} />
        <MetricCard label="Equity value" value={formatNumber(dcf?.equity_value)} />
        <MetricCard label="Terminal PV" value={formatNumber(dcf?.terminal_pv)} />
      </section>
      <ValuationBridge dcf={dcf} detail={detail.dcf_detail ?? []} />
      <SensitivityPanel
        error={sensitivityError}
        initial={initialSensitivity}
        loading={sensitivityLoading}
        onChange={handleSensitivityChange}
      />
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
  if (tab === "statements") return <StatementsView detail={detail} />;
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
