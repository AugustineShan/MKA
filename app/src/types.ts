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
  volume_unit?: string | null;
  base_revenue: number;
  unit_factor: number;
  history_revenues?: Record<string, number>;
  history_costs?: Record<string, number>;
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
  path?: string | null;
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

export type DisplayRole = "primary_model" | "primary_attachment" | "secondary_split" | "reference" | "check_only" | "deprecated" | "technical" | string;
export type DisplayPlacement = "model_table" | "secondary_table" | "reference_tab" | "technical_tab" | string;
export type DisplayDimension = "business_line" | "product" | "region" | "channel" | "subsidiary" | "customer" | "metric" | "text" | "other" | string;
export type DisplayMetric = "revenue" | "yoy" | "gross_margin" | "cost" | "volume" | "price" | "rate" | "amount" | "text" | "mixed" | string;
export type DisplayStatus = "active" | "reference" | "deprecated" | "check_only" | "missing_disclosure" | "conflict" | string;
export type DisplayDuplicatePolicy = "show" | "skip_if_equal" | "prefer_derived_and_warn" | "reference_only" | string;
export type DisplayMatchPolicy = "exact_or_declared_alias" | "declared_path" | "none" | string;

export type DisplayBlock = {
  path: string;
  role: DisplayRole;
  placement: DisplayPlacement;
  dimension?: DisplayDimension;
  metric?: DisplayMetric;
  metrics?: DisplayMetric[];
  status?: DisplayStatus;
  duplicate_policy?: DisplayDuplicatePolicy;
  match_policy?: DisplayMatchPolicy;
  attach_to?: string | null;
  title?: string | null;
};

export type DisplayWarning = {
  code: string;
  message: string;
  path?: string | null;
  severity?: "info" | "warning" | "error" | string;
};

export type Yaml1DisplayContract = {
  schema_version: number;
  mode: "declared" | "inferred" | string;
  primary_dimension?: DisplayDimension;
  blocks: DisplayBlock[];
  warnings: DisplayWarning[];
};

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

export type ReverseDcfYear = {
  index: number;
  period: string;
  revenue: number;
  fcff: number;
  nopat: number;
  da: number;
  fcff_margin: number;
  nopat_margin: number;
  da_margin: number;
  terminal_fcff_margin: number;
  fcff_to_nopat: number;
  da_to_nopat: number;
  terminal_fcff_to_nopat: number;
};

export type ReverseDcfBase = {
  schema_version: 1;
  company: {
    id: string;
    name: string;
    ticker?: string | null;
    base_period: string;
  };
  market: {
    trade_date?: string | null;
    close?: number | null;
    total_shares: number;
    market_cap: number;
    net_debt: number;
    target_enterprise_value: number;
  };
  defaults: {
    n1: number;
    n2: number;
    wacc: number;
    terminal_growth: number;
    reference_decay: number;
    terminal_capex_da_ratio: number;
  };
  bounds: {
    n1: [number, number];
    n2: [number, number];
    growth: [number, number];
    wacc: [number, number];
    terminal_growth: [number, number];
    reference_decay: [number, number];
  };
  base_model: {
    base_revenue: number;
    base_nopat: number;
    growth_metric?: "nopat" | string;
    forecast_years: number;
    current_equity_value?: number | null;
    current_per_share_value?: number | null;
    yaml1_revenue_yoy: number[];
    current_model_profit_yoy: number[];
  };
  yearly: ReverseDcfYear[];
  warnings: string[];
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
  yaml1_display_contract?: Yaml1DisplayContract | null;
  yaml1_sheets?: WorkbookSheet[];
  yaml1_stash_view?: StashBlock[];
  yaml1_assumptions_view?: Yaml1AssumptionsView | null;
  editable_assumptions?: EditableAssumption[];
  dcf_summary?: Record<string, unknown> | null;
  derived_metrics?: DerivedMetrics | null;
  rating_report?: RatingReportSettings;
  manifest?: Record<string, unknown> | null;
  tables: TableFile[];
  statement_sheets?: StatementSheet[];
  full_statement_sheets?: StatementSheet[];
  quarterly_view?: QuarterlyView | null;
  dcf_detail?: DcfDetailRow[];
  annual_revenue_breakdown?: AnnualRevenueBreakdownRow[];
  materials: FileItem[];
  da_view?: DaView | null;
};

export interface DaCategory {
  name: string;
  life_years: number;
  salvage_rate: number;
  base_gross: number;
  base_accum_dep: number;
  base_net: number;
  base_cip: number;
  policy_dep: number;
}
export interface DaSeriesPoint {
  period: string;
  ppe_depreciation: number;
  fix_assets_net: number;
  cip_balance: number;
  ppe_capex: number;
  ppe_capex_split: { maintenance: number; expansion: number; organic: number };
  other_depreciation?: number;
}
export interface DaView {
  enabled: boolean;
  base_year: number;
  align_warning: string | null;
  stock_strategy: { mode?: string; net_growth_rate?: number };
  categories: DaCategory[];
  other_depreciating_assets: { stock_strategy: { mode?: string; net_growth_rate?: number }; categories: DaCategory[] } | null;
  scale: number | null;
  base_reported_dep: number | null;
  base_cip_to_fixed: Record<string, Record<string, number>>;
  expansion_plan: Record<string, { capex_by_cat: Record<string, number>; cip_to_fixed: Record<string, number> }>;
  terminal: { capex_da_ratio: number; perpetual_growth: number };
  da_series: DaSeriesPoint[] | null;
  normalization: { passed: boolean | null; reason: string } | null;
  facts: Record<string, unknown> | null;
}

export type TabKey = "overview" | "yaml1" | "quarterly" | "statements" | "dcf" | "reverse" | "da";

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

export type PipelineStage =
  | "未初始化"
  | "初始化完毕"
  | "核心假设完毕"
  | "建模完毕"
  | "建模完毕且有DA表";

export type HomeForecastSnapshot = {
  market_cap: number | null;
  revenue_yoy: { "2026": number | null; "2027": number | null };
  profit_yoy: { "2026": number | null; "2027": number | null };
  pe: { "2026": number | null; "2027": number | null };
};

export type HomeFolderOverviewSignals = {
  pipeline_stage: PipelineStage;
  yaml1_date: string | null;
  yaml1_versions: number;
  yaml1_archive_eligible: boolean;
  root_models: { excel_count: number; lock_count: number; archive_eligible: boolean };
  workbench_materials: number;
  forecast: HomeForecastSnapshot | null;
};

export type HomeFolderOverview = {
  company_id: string;
  name: string;
  code: string;
  signals: HomeFolderOverviewSignals | null;
  error: string | null;
};

export type ArchiveModelsResult = {
  archived_yaml1: string[];
  archived_models: string[];
  deleted_locks: string[];
};

export type HomeTab = "folder-overview";
