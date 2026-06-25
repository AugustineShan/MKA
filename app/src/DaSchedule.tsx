import type { ReactNode } from "react";
import type { CompanyDetail, DaCategory } from "./types";

const fmt = (v: number | null | undefined, digits = 1): string =>
  v == null || Number.isNaN(v) ? "" : v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
const pct = (v: number | null | undefined): string => (v == null ? "" : `${(v * 100).toFixed(1)}%`);
const sum = (cats: DaCategory[], pick: (c: DaCategory) => number): number => cats.reduce((s, c) => s + pick(c), 0);

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="da-section">
      <h3 className="da-section-title">{title}</h3>
      {children}
    </section>
  );
}

function CapexMatrix({ title, years, cats, cell }: {
  title: string;
  years: string[];
  cats: DaCategory[];
  cell: (year: string, cat: DaCategory) => number | null | undefined;
}) {
  return (
    <div className="table-scroll">
      <div className="activity">{title}</div>
      <table className="financial-table">
        <thead>
          <tr>
            <th>类别</th>
            {years.map((y) => <th key={y}>{y}E</th>)}
          </tr>
        </thead>
        <tbody>
          {cats.map((c) => (
            <tr key={c.name}>
              <td>{c.name}</td>
              {years.map((y) => <td className="numeric" key={y}>{fmt(cell(y, c))}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CategoryTable({ cats }: { cats: DaCategory[] }) {
  return (
    <div className="table-scroll">
      <table className="financial-table">
        <thead>
          <tr>
            <th>类别</th><th>年限</th><th>残值率</th><th>原值</th>
            <th>累计折旧</th><th>净值</th><th>CIP</th><th>政策年折旧</th>
          </tr>
        </thead>
        <tbody>
          {cats.map((c) => (
            <tr key={c.name}>
              <td>{c.name}</td>
              <td className="numeric">{c.life_years}</td>
              <td className="numeric">{pct(c.salvage_rate)}</td>
              <td className="numeric">{fmt(c.base_gross)}</td>
              <td className="numeric">{fmt(c.base_accum_dep)}</td>
              <td className="numeric">{fmt(c.base_net)}</td>
              <td className="numeric">{fmt(c.base_cip)}</td>
              <td className="numeric">{fmt(c.policy_dep)}</td>
            </tr>
          ))}
          <tr className="subtotal-row">
            <td>合计</td>
            <td className="numeric" /><td className="numeric" />
            <td className="numeric">{fmt(sum(cats, (c) => c.base_gross))}</td>
            <td className="numeric">{fmt(sum(cats, (c) => c.base_accum_dep))}</td>
            <td className="numeric">{fmt(sum(cats, (c) => c.base_net))}</td>
            <td className="numeric">{fmt(sum(cats, (c) => c.base_cip))}</td>
            <td className="numeric">{fmt(sum(cats, (c) => c.policy_dep))}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

export default function DaSchedule({ detail }: { detail: CompanyDetail }) {
  const da = detail.da_view;
  if (!da) return null;
  const ticker = detail.summary.ticker ?? "";
  const years = Object.keys(da.expansion_plan).sort();
  const cats = da.categories;
  const otherCats = da.other_depreciating_assets?.categories ?? [];
  const policyTotal = sum(cats, (c) => c.policy_dep) + sum(otherCats, (c) => c.policy_dep);

  return (
    <div className="da-tab">
      <div className="da-info-banner">
        ⓘ 这是 /da 产出的排程展示。改假设请跑 <code>/da {ticker}</code>;
        重算请跑 <code>py -m src.forecast --ticker {ticker}</code>
      </div>

      {da.align_warning ? <div className="error-banner">{da.align_warning}</div> : null}

      <Section title={`§1 PP&E 存量快照 (base ${da.base_year})`}>
        <div className="activity">
          存量策略: {da.stock_strategy.mode ?? "—"} · g={da.stock_strategy.net_growth_rate ?? 0}
          {da.scale != null && da.base_reported_dep != null
            ? ` · scale=${da.scale.toFixed(3)} (披露 ${fmt(da.base_reported_dep)} / policy ${fmt(policyTotal)})`
            : " · scale 待补(缺 clean_annual 折旧)"}
        </div>
        <CategoryTable cats={cats} />
        {otherCats.length > 0 ? (
          <>
            <div className="activity">
              其他折旧资产(生物/油气)·g={da.other_depreciating_assets?.stock_strategy.net_growth_rate ?? 0}
              —参与折旧流量 + 稳态再投资,净值不进 fix_assets(BS held flat)
            </div>
            <CategoryTable cats={otherCats} />
          </>
        ) : null}
      </Section>

      <Section title="§2 扩张 capex 排程 + 转固">
        <CapexMatrix title="capex_by_cat (投资)" years={years} cats={cats}
          cell={(y, c) => da.expansion_plan[y]?.capex_by_cat?.[c.name]} />
        <CapexMatrix title="cip_to_fixed (转固起折旧)" years={years} cats={cats}
          cell={(y, c) => da.expansion_plan[y]?.cip_to_fixed?.[c.name]} />
        <div className="table-scroll">
          <table className="financial-table">
            <thead>
              <tr>
                <th>存量 CIP 转固</th>
                {years.map((y) => <th key={y}>{y}E</th>)}
              </tr>
            </thead>
            <tbody>
              {cats.map((c) => (
                <tr key={c.name}>
                  <td>{c.name}</td>
                  {years.map((y) => <td className="numeric" key={y}>{fmt(da.base_cip_to_fixed[y]?.[c.name])}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <Section title="§3 da_series 结果 (逐年)">
        {da.da_series == null ? (
          <div className="error-banner">
            请先 <code>py -m src.forecast --ticker {ticker}</code> 重跑生成 da_series
          </div>
        ) : (
          <>
            <div className="table-scroll">
              <table className="financial-table">
                <thead>
                  <tr>
                    <th>年</th><th>PP&E 折旧</th>
                    {otherCats.length > 0 ? <th>其他折旧</th> : null}
                    <th>固定资产净值</th><th>CIP 余额</th>
                    <th>capex 合计</th><th>维持</th><th>扩张</th><th>有机</th>
                  </tr>
                </thead>
                <tbody>
                  {da.da_series.map((p) => (
                    <tr key={p.period}>
                      <td>{p.period}E</td>
                      <td className="numeric">{fmt(p.ppe_depreciation)}</td>
                      {otherCats.length > 0 ? <td className="numeric">{fmt(p.other_depreciation)}</td> : null}
                      <td className="numeric">{fmt(p.fix_assets_net)}</td>
                      <td className="numeric">{fmt(p.cip_balance)}</td>
                      <td className="numeric">{fmt(p.ppe_capex)}</td>
                      <td className="numeric">{fmt(p.ppe_capex_split.maintenance)}</td>
                      <td className="numeric">{fmt(p.ppe_capex_split.expansion)}</td>
                      <td className="numeric">{fmt(p.ppe_capex_split.organic)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {da.normalization ? (
              <div className={da.normalization.passed ? "da-normalization-passed" : "da-normalization-failed"}>
                终值归一化门: {da.normalization.passed ? "passed" : "failed"} — {da.normalization.reason}
              </div>
            ) : null}
          </>
        )}
      </Section>

      <Section title="§4 历史 roll-forward 证据 (da_facts)">
        {da.facts == null ? (
          <div className="activity">无 da_facts_latest.json</div>
        ) : (
          <details>
            <summary>展开历史 roll-forward (per 类别 × 近 5 年) + policy</summary>
            <pre className="da-facts-raw">{JSON.stringify(da.facts, null, 2)}</pre>
          </details>
        )}
      </Section>
    </div>
  );
}
