export type Kind = 'well' | 'truck' | 'lib';

export interface Approval { by: string; at: string; plan_version: number; kind: Kind; name: string }

export interface PlanItem {
  key: string; kind: Kind; rank: number; name: string; neighborhood?: string | null;
  latitude: number; longitude: number; tract_geo_id?: string | null;
  priority_score: number; predicted_offset_f?: number | null; expected_air_temp_f?: number | null;
  measured?: boolean; measured_offset_f?: number | null;
  why?: { feature: string; contribution_f: number }[];
  residents_65_plus?: number | null; households_without_car?: number | null; poverty_rate?: number | null;
  tract_population?: number | null; km_to_indoor_cooling?: number | null; nearest_cooling_name?: string | null;
  // library
  address?: string | null; hours_today?: string; extend_to?: string | null; served_tracts?: string[];
  served_population?: number; served_65_plus?: number; radius_km?: number;
  approval?: Approval | null;
}

export interface Constraints {
  trucks: number; wellness_teams: number; libraries: number;
  closed_sites: string[]; cutoff_f: number; ranking: 'balanced' | 'heat' | 'vulnerable';
}

export interface Day { date?: string | null; weekday: string; label?: string | null; high_f?: number | null; short_forecast?: string | null }

export interface DiffEntry { key: string; name: string }
export type PlanDiff = Partial<Record<Kind, { added: DiffEntry[]; removed: DiffEntry[] }>>;
export interface Warning { kind: Kind; reason: string; unapproved: string[]; message: string }

export interface Summary {
  hot_tracts: number; residents_in_hot_tracts: number; share_of_65_plus_in_hot_tracts: number;
  share_of_hot_65_plus_reached: number; top50_heat_vs_vulnerability_overlap: number; counts: Record<Kind, number>;
}

export interface Plan {
  version: number; created_at: string; created_by: string; source: string;
  day: Day; constraints: Constraints; items: PlanItem[]; approved: Record<string, Approval>;
  skipped: string[]; warnings: Warning[]; diff: PlanDiff; changes: string[]; summary: Summary | null;
  can_undo: boolean; ranking_presets: Record<string, number>; limits: Record<string, number>;
  stand_down?: boolean; stand_down_reason?: string | null;
}

export interface TractProps {
  tract_geo_id: string; neighborhood?: string | null; latitude: number; longitude: number;
  predicted_offset_f: number; measured_readings?: number; measured_offset_f?: number | null;
  total_pop: number; pop_65_plus: number; pct_65_plus?: number; poverty_rate?: number; no_vehicle_rate?: number;
  median_income?: number; vulnerability_index: number; area_km2?: number;
  nearest_ac_name?: string | null; nearest_ac_category?: string | null; km_to_ac?: number | null;
}

export interface TractFeature { type: 'Feature'; id?: string; properties: TractProps; geometry: GeoJSON.Geometry }

export interface Site {
  site_name: string; site_category: string; address?: string | null; latitude: number; longitude: number;
  is_current_cooling_site?: boolean | null; indoor_air_conditioned?: boolean | null; open_24_7?: boolean | null;
  hours_of_operation?: string | null; service_hours?: string | null;
}

export interface Layers { tracts: { type: 'FeatureCollection'; features: TractFeature[] }; sites: Site[]; fetched_at: string }

export type ChatEvent =
  | { type: 'session'; session_id: string }
  | { type: 'tool'; name: string }
  | { type: 'text'; text: string; author?: string }
  | { type: 'plan'; plan: Plan }
  | { type: 'error'; message: string }
  | { type: 'done' };
