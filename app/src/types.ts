export type CompanySummary = {
  id: string;
  name: string;
  code: string;
  ticker?: string | null;
  path: string;
  has_yaml1: boolean;
  has_defaults: boolean;
  has_forecast: boolean;
  has_core_assumption: boolean;
  has_materials: boolean;
  per_share_value?: number | null;
  base_period?: string | null;
  forecast_years?: number | null;
  warnings_count?: number | null;
  backtest_status?: string | null;
  updated_at?: number | null;
};

export type TableFile = {
  name: string;
  path: string;
  csv: string;
};

export type WorkbookSheet = {
  name: string;
  description?: string | null;
  columns: string[];
  rows: Array<Record<string, string | number | null | undefined>>;
};

export type Yaml1RevenueSegment = {
  key: string;
  name: string;
  family: string;
  base_year: number;
  base_volume?: number | null;
  base_price?: number | null;
  base_revenue: number;
  unit_factor: number;
  history_revenues?: Record<string, number>;
  history_volumes?: Record<string, number>;
  revenues: Record<string, number>;
  yoys: Record<string, number>;
  volumes?: Record<string, number>;
  note?: string | null;
};

export type Yaml1RevenueDriver = {
  segment: string;
  driver: string;
  values: Record<string, number>;
};

export type Yaml1RevenueView = {
  base_year: number;
  years: string[];
  base_revenue: number;
  revenues: Record<string, number>;
  yoy: Record<string, number>;
  segments: Yaml1RevenueSegment[];
  drivers: Yaml1RevenueDriver[];
  source?: string | null;
  note?: string | null;
};

export type Yaml1Presentation = {
  schema_version?: number;
  mode?: "llm" | "fallback" | string;
  provider?: string | null;
  model?: string | null;
  title?: string;
  subtitle?: string;
  business_question?: string;
  display_strategy?: string;
  primary_dimension?: string;
  segment_order?: string[];
  driver_labels?: Record<string, string>;
  insights?: string[];
  risks?: string[];
  source_paths?: string[];
  created_at?: string;
};

export type StatementRow = {
  field: string;
  label: string;
  display_label?: string;
  category: string;
  category_label: string;
  role: "normal" | "subtotal" | "total";
  display_role?: "primary" | "metric" | "supporting" | "technical" | "debug" | string;
  is_technical?: boolean;
  technical_reason?: string | null;
  combo_of?: string[];
  level: number;
  is_zero: boolean;
  values: Record<string, number | null>;
};

export type StatementSheet = {
  key: string;
  name: string;
  title: string;
  unit: string;
  path: string;
  years: string[];
  rows: StatementRow[];
};

export type DerivedMetrics = {
  schema_version?: number;
  generated_at?: string;
  ticker?: string | null;
  name?: string | null;
  base_period?: string | number | null;
  periods?: string[];
  market_snapshot?: Record<string, number | string | null | undefined>;
  annual?: Record<string, Record<string, number | null | undefined>>;
  quarterly?: {
    periods?: string[];
    rows?: QuarterlyRow[];
    metrics_by_period?: Record<string, Record<string, number | null | undefined>>;
    [key: string]: unknown;
  } | null;
  valuation?: Record<string, unknown>;
  rating_report_rows?: Array<{
    metric: string;
    label: string;
    values: Record<string, number | null | undefined>;
  }>;
  metric_labels?: Record<string, string>;
  source_files?: Record<string, string>;
  warnings?: string[];
};

export type QuarterState = "actual" | "inherit" | "manual" | "q4" | string;

export type QuarterlyRow = {
  field: string;
  label: string;
  category: string;
  role: "leaf" | "total" | string;
  format?: "number" | "percent" | string;
  is_zero?: boolean;
  highlight?: boolean;
  values: Record<string, number | null>;
  states: Record<string, QuarterState>;
};

export type QuarterlyFlag = {
  ratio: string;
  implied: number;
  band_min: number;
  band_max: number;
  msg?: string;
};

export type QuarterlyView = {
  year: number;
  periods?: string[];
  quarter_states: Record<string, QuarterState>;
  period_states?: Record<string, QuarterState>;
  rows: QuarterlyRow[];
  annual: Record<string, number | null>;
  variance: Record<string, Record<string, number>>;
  q4_flags: QuarterlyFlag[];
};

export type FileItem = {
  name: string;
  path: string;
  kind: string;
  size: number;
  modified_at?: number | null;
};

export type AnnualRevenueBreakdownRow = {
  year: number;
  period?: string;
  period_type?: "annual" | "h1" | string;
  period_label?: string;
  dimension: "industry" | "product" | "region" | "sales_model" | string;
  dimension_label: string;
  item_name: string;
  revenue_yuan?: number | null;
  revenue_pct?: number | null;
  revenue_yoy_pct?: number | null;
  cost_yuan?: number | null;
  cost_yoy_pct?: number | null;
  gross_margin_pct?: number | null;
  gross_margin_change?: string | null;
  source_table: string;
  source_line: number;
  confidence: string;
  source_file?: string | null;
};

// ───────── stash type-dispatch (universal: any company shape) ─────────
export type StashBlock = {
  name: string;
  type: "list" | "series_table" | "attr_table" | "text_dict" | "scalar_table" | "kv";
  note?: string | null;
  unit?: string | null;
  caveat?: string | null;
  items: Array<StashItem | StashBlock | string>;
  extras?: StashBlock[];
  col_labels?: Record<string, string> | null;
};

export type StashItem =
  | { key?: string; label: string; values: Record<string, number | null>; note?: string | null }
  | { label: string; text: string }
  | { label: string; value: number | string };

// ───────── assumptions view ─────────
export type AssumptionsKnob = {
  path: string;
  src: string;
  values: number[];
  note?: string | null;
  is_override: boolean;
};

export type AssumptionsSection = {
  key: string;
  title: string;
  knobs: AssumptionsKnob[];
};

export type TerminalView = {
  explicit_end?: number | null;
  to_year?: number | null;
  kind?: string | null;
  fade_paths?: string[];
  hold_paths?: string[];
  perpetual_growth?: number | null;
  src?: string | null;
};

export type TraceabilityItem = { name: string; text: string };

export type Yaml1AssumptionsView = {
  years: string[];
  base_period: string;
  sections: AssumptionsSection[];
  terminal: TerminalView;
  traceability: TraceabilityItem[];
};

export type EditableAssumptionCell = {
  year: string;
  pointer: string;
  value: number | null;
};

export type EditableAssumption = {
  id: string;
  label: string;
  group: "result" | "revenue_driver" | "standard_knob" | "terminal" | "other";
  path: string;
  family?: string | null;
  unit: "pct" | "decimal" | "abs_mn" | "number" | "unknown";
  format: "percent" | "number" | "integer";
  source: string;
  cells: EditableAssumptionCell[];
  note?: string | null;
  src?: string | null;
};

export type AssumptionPatch = {
  pointer: string;
  old_value: number | null;
  new_value: number | null;
};

// ───────── dcf detail ─────────
export type DcfDetailRow = {
  period: number;
  fcff: number;
  discount_factor: number;
  pv_fcff: number;
  nopat: number;
  da: number;
  capex: number;
  delta_nwc: number;
};

export type AssumptionPreview = {
  dcf_summary?: Record<string, unknown> | null;
  derived_metrics?: DerivedMetrics | null;
  dcf_detail?: DcfDetailRow[];
  statement_sheets?: StatementSheet[];
  result_rows: StatementRow[];
  warnings?: Array<Record<string, unknown>>;
  errors?: Array<Record<string, unknown>>;
};

export type CompanyDetail = {
  summary: CompanySummary;
  core_assumption_md?: string | null;
  yaml1_path?: string | null;
  yaml1_text?: string | null;
  yaml1_revenue_view?: Yaml1RevenueView | null;
  yaml1_presentation?: Yaml1Presentation | null;
  yaml1_sheets?: WorkbookSheet[];
  yaml1_stash_view?: StashBlock[];
  yaml1_assumptions_view?: Yaml1AssumptionsView | null;
  editable_assumptions?: EditableAssumption[];
  dcf_summary?: Record<string, unknown> | null;
  derived_metrics?: DerivedMetrics | null;
  manifest?: Record<string, unknown> | null;
  tables: TableFile[];
  statement_sheets?: StatementSheet[];
  full_statement_sheets?: StatementSheet[];
  quarterly_view?: QuarterlyView | null;
  dcf_detail?: DcfDetailRow[];
  annual_revenue_breakdown?: AnnualRevenueBreakdownRow[];
  materials: FileItem[];
};

export type TabKey = "overview" | "yaml1" | "quarterly" | "statements" | "dcf";

export type SettingsField = {
  key: string;
  label: string;
  section: "workspace" | "data" | "llm" | string;
  secret: boolean;
  placeholder?: string;
  configured: boolean;
  value?: string;
  masked?: string | null;
};

export type SettingsValidation = {
  path: string;
  exists: boolean;
  is_dir: boolean;
  writable: boolean;
  company_count: number;
};

export type RatingReportSettings = {
  data_start_year: number;
  data_end_year: number;
  forecast_start_year: number;
  forecast_end_year: number;
};

export type AppSettings = {
  env_path: string;
  root: string;
  companies_dir: string;
  default_companies_dir: string;
  fields: SettingsField[];
  validation: SettingsValidation;
  rating_report?: RatingReportSettings;
};
