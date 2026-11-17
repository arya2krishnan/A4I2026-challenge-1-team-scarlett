export const fmt = (n: number | null | undefined): string => {
  if (n == null || Number.isNaN(n)) return '–';
  return n >= 1e6 ? (n / 1e6).toFixed(2) + 'M' : n >= 1e4 ? Math.round(n / 1e3) + 'k' : n >= 1e3 ? (n / 1e3).toFixed(1) + 'k' : String(Math.round(n));
};
export const sgn = (v: number | null | undefined, d = 1): string =>
  v == null ? '–' : (v > 0 ? '+' : v < 0 ? '−' : '±') + Math.abs(v).toFixed(d) + '°';
export const pct = (v: number | null | undefined): string => (v == null ? '–' : Math.round(v * 100) + '%');
export const DAY_NAME: Record<string, string> = { mon: 'Monday', tue: 'Tuesday', wed: 'Wednesday', thu: 'Thursday', fri: 'Friday', sat: 'Saturday', sun: 'Sunday' };
export const FEATURE_LABEL: Record<string, string> = {
  lake_distance_band: 'far from lake', dist_to_lake_km: 'far from lake', dist_to_loop_km: 'distance to Loop',
  pop_density_km2: 'density', building_era: 'housing age', median_year_structure_built: 'housing age',
  building_share: 'buildings', green_share: 'little green', paved_use_share: 'paved land', road_km_per_km2: 'streets',
};
export const timeOf = (iso: string): string => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
};
