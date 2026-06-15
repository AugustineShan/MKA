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
  category: string;
  category_label: string;
  role: "normal" | "subtotal" | "total";
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

export type FileItem = {
  name: string;
  path: string;
  kind: string;
  size: number;
  modified_at?: number | null;
};

export type CompanyDetail = {
  summary: CompanySummary;
  core_assumption_md?: string | null;
  yaml1_path?: string | null;
  yaml1_text?: string | null;
  yaml1_revenue_view?: Yaml1RevenueView | null;
  yaml1_presentation?: Yaml1Presentation | null;
  yaml1_sheets?: WorkbookSheet[];
  dcf_summary?: Record<string, unknown> | null;
  manifest?: Record<string, unknown> | null;
  tables: TableFile[];
  statement_sheets?: StatementSheet[];
  materials: FileItem[];
};

export type TabKey = "overview" | "assumptions" | "yaml1" | "dcf" | "materials";
