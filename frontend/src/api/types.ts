export interface ResultSummary {
  opening_status: string | null;
  opening_status_label: string;
  winning_vendor_name: string | null;
  winning_bid_amount: string | null;
  winning_rate: string | null;
  winning_rate_basis: string | null;
  actual_sajeong_rate: string | null;
  bid_count: number | null;
}

export interface Notice {
  id: number;
  notice_number: string;
  notice_revision: string;
  title: string;
  agency_name: string | null;
  demand_agency_name: string | null;
  procurement_type: string | null;
  issuing_authority_type: string | null;
  contract_method: string | null;
  award_method: string | null;
  region_name: string | null;
  industry_name: string | null;
  announcement_date: string | null;
  bid_deadline: string | null;
  opening_date: string | null;
  base_amount: string | null;
  presumed_price: string | null;
  estimated_price: string | null;
  estimated_price_status: string | null;
  lower_limit_rate: string | null;
  phase: string;
  data_status: string;
  data_status_label: string;
  is_latest_revision: boolean;
  source_name: string;
  notice_url: string | null;
  result: ResultSummary | null;
  favorite?: boolean;
}

export interface Page<T> {
  total: number;
  page: number;
  size: number;
  items: T[];
}

export interface CalcResult {
  name: string;
  value: string;
  unit: string;
  formula: string;
  inputs: Record<string, unknown>;
  price_status: string;
  assumption_based: boolean;
  status_label: string;
  warnings: string[];
  extra: Record<string, string>;
}

export interface Summary {
  n: number;
  mean: number | null;
  median: number | null;
  q1: number | null;
  q3: number | null;
  std: number | null;
  min: number | null;
  max: number | null;
  outliers: number;
  outlier_bounds: number[] | null;
  outliers_excluded: boolean;
  warnings: string[];
}

export interface Stratum {
  label: string;
  conditions: Record<string, string | null>;
  summary: Summary;
  groups: { key: Record<string, string | null>; summary: Summary }[];
  trend: { period: string; n: number; median: number | null; mean: number | null }[];
}

export interface StatsResult {
  metric: string;
  metric_label: string;
  metric_definition: string;
  n_records: number;
  missing_count: number;
  missing_rate: number | null;
  strata: Stratum[];
  pooled: Summary | null;
  warnings: string[];
  sources: Record<string, number>;
  period: { from: string | null; to: string; basis: string; preset?: string };
  disclaimer: string;
  dataset_version: string;
  analysis_run_id?: number;
  histograms?: Record<string, { from: number; to: number; count: number }[]>;
}

export interface Scenario {
  name: string;
  label: string;
  method: string;
  price_status: string;
  assumed_sajeong_rate?: string;
  assumed_estimated_price?: string;
  assumed_lower_limit?: string;
  candidate_amount: string;
  bid_rate_vs_base_amount: string;
  historical_check: { n: number; below_lower_limit: number; above_estimated_price: number; within_range: number; meaning: string };
  profit?: { status: string; profit: string | null; margin_pct: string | null; bid_supply_amount?: string; cost_supply_total?: string; flags: string[]; warnings: string[] };
  risk_flags: string[];
  explanation: { steps: string[] };
}

export interface RecommendResult {
  status: string;
  label: string;
  base_amount: string;
  lower_limit: { rate_pct: string; source: string; a_value: string | null; formula: string; rule_code: string | null; verified: boolean };
  sample: { n: number; sajeong_summary: Partial<Summary>; period: { from: string | null; to: string }; conditions: Record<string, string | null>; notice_ids: number[] };
  scenarios: Scenario[];
  warnings: string[];
  disclaimer: string;
  notice: { id: number; notice_number: string; title: string; bid_deadline: string | null };
  rule_selection: { rule_selection_warnings: string[]; matched_rules: string[]; undetermined_rules: string[] };
  cost?: { break_even: Record<string, string>; supply_total: string | null; warnings: string[]; complete: boolean };
  dataset_version: string;
  analysis_run_id?: number;
}
