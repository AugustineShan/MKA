import type { ReactNode } from "react";
import type { CompanyDetail, DaCategory } from "./types";

const fmt = (v: number | null | undefined, digits = 1): string =>
  v == null || Number.isNaN(v)
    ? "-"
    : v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });

const pct = (v: number | null | undefined): string => (v == null || Number.isNaN(v) ? "-" : `${(v * 100).toFixed(1)}%`);

const sum = (cats: DaCategory[], pick: (c: DaCategory) => number): number => cats.reduce((s, c) => s + pick(c), 0);

const valueClass = (v: number | null | undefined, extra = ""): string =>
  ["numeric", v != null && v < 0 ? "negative" : "", extra].filter(Boolean).join(" ");

const forecastYear = (year: string): string => (/^\d+$/.test(year) ? `${year}E` : year);

function Section({
  eyebrow,
  title,
  meta,
  children,
}: {
  eyebrow: string;
  title: string;
  meta?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="da-section card">
      <div className="da-section-head">
        <div>
          <div className="eyebrow">{eyebrow}</div>
          <h2>{title}</h2>
        </div>
        {meta ? <div className="da-section-meta">{meta}</div> : null}
      </div>
      {children}
    </section>
  );
}

function DaStat({ label, value, caption, tone = "default" }: {
  label: string;
  value: string;
  caption?: string;
  tone?: "default" | "accent" | "danger";
}) {
  return (
    <div className={`da-stat ${tone !== "default" ? `da-stat-${tone}` : ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      {caption ? <small>{caption}</small> : null}
    </div>
  );
}

function TableBlock({ title, note, children }: { title: string; note?: string; children: ReactNode }) {
  return (
    <div className="da-table-block">
      <div className="da-table-head">
        <strong>{title}</strong>
        {note ? <span>{note}</span> : null}
      </div>
      <div className="table-scroll workbook-scroll da-table-scroll">{children}</div>
    </div>
  );
}

function CapexMatrix({ title, years, cats, cell }: {
  title: string;
  years: string[];
  cats: DaCategory[];
  cell: (year: string, cat: DaCategory) => number | null | undefined;
}) {
  return (
    <TableBlock title={title} note="单位：百万元">
      <table className="financial-table da-table">
        <thead>
          <tr>
            <th>类别</th>
            {years.map((y) => <th className="numeric" key={y}>{forecastYear(y)}</th>)}
          </tr>
        </thead>
        <tbody>
          {cats.map((c) => (
            <tr key={c.name}>
              <td>{c.name}</td>
              {years.map((y) => {
                const value = cell(y, c);
                return <td className={valueClass(value)} key={y}>{fmt(value)}</td>;
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </TableBlock>
  );
}

function CategoryTable({ cats, title }: { cats: DaCategory[]; title: string }) {
  return (
    <TableBlock title={title} note="单位：百万元；残值率除外">
      <table className="financial-table da-table da-category-table">
        <thead>
          <tr>
            <th>类别</th>
            <th className="numeric">年限</th>
            <th className="numeric">残值率</th>
            <th className="numeric">原值</th>
            <th className="numeric">累计折旧</th>
            <th className="numeric">净值</th>
            <th className="numeric">CIP</th>
            <th className="numeric">政策年折旧</th>
          </tr>
        </thead>
        <tbody>
          {cats.map((c) => (
            <tr key={c.name}>
              <td>{c.name}</td>
              <td className="numeric">{fmt(c.life_years, 0)}</td>
              <td className="numeric">{pct(c.salvage_rate)}</td>
              <td className={valueClass(c.base_gross)}>{fmt(c.base_gross)}</td>
              <td className={valueClass(c.base_accum_dep)}>{fmt(c.base_accum_dep)}</td>
              <td className={valueClass(c.base_net)}>{fmt(c.base_net)}</td>
              <td className={valueClass(c.base_cip)}>{fmt(c.base_cip)}</td>
              <td className={valueClass(c.policy_dep)}>{fmt(c.policy_dep)}</td>
            </tr>
          ))}
          <tr className="subtotal-row">
            <td>合计</td>
            <td className="numeric">-</td>
            <td className="numeric">-</td>
            <td className={valueClass(sum(cats, (c) => c.base_gross))}>{fmt(sum(cats, (c) => c.base_gross))}</td>
            <td className={valueClass(sum(cats, (c) => c.base_accum_dep))}>{fmt(sum(cats, (c) => c.base_accum_dep))}</td>
            <td className={valueClass(sum(cats, (c) => c.base_net))}>{fmt(sum(cats, (c) => c.base_net))}</td>
            <td className={valueClass(sum(cats, (c) => c.base_cip))}>{fmt(sum(cats, (c) => c.base_cip))}</td>
            <td className={valueClass(sum(cats, (c) => c.policy_dep))}>{fmt(sum(cats, (c) => c.policy_dep))}</td>
          </tr>
        </tbody>
      </table>
    </TableBlock>
  );
}

export default function DaSchedule({ detail }: { detail: CompanyDetail }) {
  const da = detail.da_view;
  if (!da) return null;

  const ticker = detail.summary.ticker ?? detail.summary.code ?? "";
  const years = Object.keys(da.expansion_plan).sort();
  const cats = da.categories;
  const otherCats = da.other_depreciating_assets?.categories ?? [];
  const categoryCount = cats.length + otherCats.length;
  const policyTotal = sum(cats, (c) => c.policy_dep) + sum(otherCats, (c) => c.policy_dep);
  const baseNetTotal = sum(cats, (c) => c.base_net);
  const baseCipTotal = sum(cats, (c) => c.base_cip);
  const planTotal = years.reduce(
    (total, year) => total + sum(cats, (c) => da.expansion_plan[year]?.capex_by_cat?.[c.name] ?? 0),
    0,
  );
  const seriesLast = da.da_series?.[da.da_series.length - 1];
  const yearRange = years.length ? `${forecastYear(years[0])} - ${forecastYear(years[years.length - 1])}` : "未配置";
  const stockGrowth = da.stock_strategy.net_growth_rate ?? 0;
  const otherGrowth = da.other_depreciating_assets?.stock_strategy.net_growth_rate;
  const factsCount = da.facts ? Object.keys(da.facts).length : 0;

  return (
    <div className="view-stack da-tab">
      <section className="da-hero">
        <div className="da-hero-copy">
          <div className="eyebrow">Fixed asset schedule</div>
          <h2>重资产排程</h2>
          <p>
            只读展示 `/da` 生成的 PP&E 存量、扩张 CAPEX、转固与逐年折旧结果。改假设请跑 <code>/da {ticker}</code>，
            重算请跑 <code>py -m src.forecast --ticker {ticker}</code>。
          </p>
        </div>
        <div className="da-hero-rail">
          <div>
            <span>Base</span>
            <strong>{da.base_year}</strong>
          </div>
          <div>
            <span>Forecast</span>
            <strong>{yearRange}</strong>
          </div>
        </div>
      </section>

      {da.align_warning ? <div className="error-banner da-error">{da.align_warning}</div> : null}

      <section className="da-stat-grid">
        <DaStat label="类别数" value={fmt(categoryCount, 0)} caption="PP&E + 其他折旧资产" />
        <DaStat label="政策年折旧" value={fmt(policyTotal)} caption="百万元" tone="accent" />
        <DaStat label="披露折旧" value={fmt(da.base_reported_dep)} caption={da.scale == null ? "待补 scale" : `scale ${da.scale.toFixed(3)}`} />
        <DaStat label="存量净值 / CIP" value={`${fmt(baseNetTotal)} / ${fmt(baseCipTotal)}`} caption="百万元" />
        <DaStat label="扩张 CAPEX" value={fmt(planTotal)} caption={yearRange} />
        <DaStat
          label="终值门"
          value={da.normalization?.passed == null ? "-" : da.normalization.passed ? "Passed" : "Failed"}
          caption={`CAPEX/DA ${fmt(da.terminal.capex_da_ratio, 2)} · g ${pct(da.terminal.perpetual_growth)}`}
          tone={da.normalization?.passed === false ? "danger" : "default"}
        />
      </section>

      <Section
        eyebrow={`Section 1 · Base ${da.base_year}`}
        title="PP&E 存量快照"
        meta={
          <>
            存量策略：{da.stock_strategy.mode ?? "-"} · g {pct(stockGrowth)}
          </>
        }
      >
        <CategoryTable cats={cats} title="PP&E 类别" />
        {otherCats.length > 0 ? (
          <CategoryTable
            cats={otherCats}
            title={`其他折旧资产 · ${da.other_depreciating_assets?.stock_strategy.mode ?? "-"} · g ${pct(otherGrowth)}`}
          />
        ) : null}
      </Section>

      <Section eyebrow="Section 2" title="扩张 CAPEX 排程 + 转固" meta={`预测期：${yearRange}`}>
        <div className="da-table-grid">
          <CapexMatrix
            title="capex_by_cat · 投资"
            years={years}
            cats={cats}
            cell={(y, c) => da.expansion_plan[y]?.capex_by_cat?.[c.name]}
          />
          <CapexMatrix
            title="cip_to_fixed · 转固起折旧"
            years={years}
            cats={cats}
            cell={(y, c) => da.expansion_plan[y]?.cip_to_fixed?.[c.name]}
          />
        </div>
        <TableBlock title="存量 CIP 转固" note="单位：百万元">
          <table className="financial-table da-table">
            <thead>
              <tr>
                <th>类别</th>
                {years.map((y) => <th className="numeric" key={y}>{forecastYear(y)}</th>)}
              </tr>
            </thead>
            <tbody>
              {cats.map((c) => (
                <tr key={c.name}>
                  <td>{c.name}</td>
                  {years.map((y) => {
                    const value = da.base_cip_to_fixed[y]?.[c.name];
                    return <td className={valueClass(value)} key={y}>{fmt(value)}</td>;
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </TableBlock>
      </Section>

      <Section
        eyebrow="Section 3"
        title="da_series 结果"
        meta={seriesLast ? `末年固定资产净值 ${fmt(seriesLast.fix_assets_net)}` : "待生成"}
      >
        {da.da_series == null ? (
          <div className="da-empty">
            <h2>尚未生成逐年结果</h2>
            <p>
              请先 <code>py -m src.forecast --ticker {ticker}</code> 重跑生成 da_series。
            </p>
          </div>
        ) : (
          <>
            <TableBlock title="逐年折旧与资本开支" note="单位：百万元">
              <table className="financial-table da-table da-series-table">
                <thead>
                  <tr>
                    <th>年</th>
                    <th className="numeric">PP&E 折旧</th>
                    {otherCats.length > 0 ? <th className="numeric">其他折旧</th> : null}
                    <th className="numeric">固定资产净值</th>
                    <th className="numeric">CIP 余额</th>
                    <th className="numeric">CAPEX 合计</th>
                    <th className="numeric">维持</th>
                    <th className="numeric">扩张</th>
                    <th className="numeric">有机</th>
                  </tr>
                </thead>
                <tbody>
                  {da.da_series.map((p) => (
                    <tr key={p.period}>
                      <td>{forecastYear(p.period)}</td>
                      <td className={valueClass(p.ppe_depreciation)}>{fmt(p.ppe_depreciation)}</td>
                      {otherCats.length > 0 ? <td className={valueClass(p.other_depreciation)}>{fmt(p.other_depreciation)}</td> : null}
                      <td className={valueClass(p.fix_assets_net)}>{fmt(p.fix_assets_net)}</td>
                      <td className={valueClass(p.cip_balance)}>{fmt(p.cip_balance)}</td>
                      <td className={valueClass(p.ppe_capex)}>{fmt(p.ppe_capex)}</td>
                      <td className={valueClass(p.ppe_capex_split.maintenance)}>{fmt(p.ppe_capex_split.maintenance)}</td>
                      <td className={valueClass(p.ppe_capex_split.expansion)}>{fmt(p.ppe_capex_split.expansion)}</td>
                      <td className={valueClass(p.ppe_capex_split.organic)}>{fmt(p.ppe_capex_split.organic)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableBlock>
            {da.normalization ? (
              <div className={`da-normalization ${da.normalization.passed ? "da-normalization-passed" : "da-normalization-failed"}`}>
                <strong>终值归一化门：{da.normalization.passed ? "passed" : "failed"}</strong>
                <span>{da.normalization.reason}</span>
              </div>
            ) : null}
          </>
        )}
      </Section>

      <Section eyebrow="Section 4" title="历史 roll-forward 证据" meta={da.facts ? `${fmt(factsCount, 0)} 个顶层字段` : "无证据文件"}>
        {da.facts == null ? (
          <div className="activity da-muted-row">无 da_facts_latest.json</div>
        ) : (
          <details className="da-details">
            <summary>
              <strong>展开历史 roll-forward</strong>
              <span>per 类别 × 近 5 年 + policy</span>
            </summary>
            <pre className="da-facts-raw">{JSON.stringify(da.facts, null, 2)}</pre>
          </details>
        )}
      </Section>
    </div>
  );
}
