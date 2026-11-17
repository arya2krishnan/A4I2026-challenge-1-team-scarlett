import type { Kind, Plan, TractProps } from './types';

export type LensKey = 'plan' | 'temp' | 'offset' | 'exposure' | 'vuln' | 'bivar';

export const LENSES: { k: LensKey; t: string; d: string; sw: string }[] = [
  { k: 'plan', t: 'Dispatch plan', d: 'Tracts colored by intervention', sw: 'linear-gradient(90deg,#cf2f6b 33%,#0b8f86 33% 66%,#4b4fd8 66%)' },
  { k: 'temp', t: 'Street-level heat (°F)', d: 'Forecast high + modelled offset', sw: 'linear-gradient(90deg,#fde3a0,#dc5230,#741326)' },
  { k: 'offset', t: 'Heat differential', d: '° hotter/cooler than city average', sw: 'linear-gradient(90deg,#2d5f9a,#e9e4da,#c23b2b)' },
  { k: 'exposure', t: 'People × excess heat', d: 'Residents/km² × ° above average', sw: 'linear-gradient(90deg,#fbf3d5,#f2853f,#741326)' },
  { k: 'vuln', t: 'Vulnerable residents', d: 'Vulnerability index (65+, no car, poverty)', sw: 'linear-gradient(90deg,#f3f0f7,#7a62ad,#4b2f80)' },
  { k: 'bivar', t: 'Heat × vulnerability', d: 'Where both are high', sw: 'linear-gradient(135deg,#e8e6e1,#b23a3a)' },
];

export const COLOR: Record<Kind, string> = { well: '#cf2f6b', truck: '#0b8f86', lib: '#4b4fd8' };
export const LABEL: Record<Kind, string> = { well: '🩺 Wellness checks', truck: '🚚 Hydration truck', lib: '📚 Extend library hours' };
export const EMOJI: Record<Kind, string> = { well: '🩺', truck: '🚚', lib: '📚' };
export const BIV = [['#e8e6e1', '#e6c7a3', '#e39a5f'], ['#b9c1d9', '#c9a78f', '#d4704a'], ['#7c8fc4', '#9a7b9c', '#b23a3a']];

function hex2rgb(h: string): number[] { const n = parseInt(h.slice(1), 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; }
export function ramp(stops: string[]): (v: number) => string {
  const c = stops.map(hex2rgb);
  return (v: number) => {
    v = Math.max(0, Math.min(1, Number.isFinite(v) ? v : 0));
    const i = Math.min(c.length - 2, Math.floor(v * (c.length - 1)));
    const f = v * (c.length - 1) - i;
    const a = c[i], b = c[i + 1];
    return `rgb(${Math.round(a[0] + (b[0] - a[0]) * f)},${Math.round(a[1] + (b[1] - a[1]) * f)},${Math.round(a[2] + (b[2] - a[2]) * f)})`;
  };
}
export const heatRamp = ramp(['#fbf3d5', '#fde3a0', '#fbb867', '#f2853f', '#dc5230', '#b02a2a', '#741326']);
export const divRamp = ramp(['#2d5f9a', '#7fa8cf', '#e9e4da', '#f0a06a', '#c23b2b']);
export const purpleRamp = ramp(['#f3f0f7', '#d4cbe6', '#a897cc', '#7a62ad', '#4b2f80']);

const q = (a: number[], p: number) => (a.length ? a[Math.floor(p * (a.length - 1))] : 0);
const sorted = (a: number[]) => a.filter(Number.isFinite).sort((x, y) => x - y);
export const density = (t: TractProps) => (t.total_pop || 0) / Math.max(t.area_km2 || 0, 0.05);

export interface LensStats { o02: number; o98: number; o33: number; o66: number; v33: number; v66: number; vmin: number; vmax: number; exmax: number; absmax: number }

export function lensStats(tracts: TractProps[]): LensStats {
  const o = sorted(tracts.map(t => t.predicted_offset_f));
  const v = sorted(tracts.map(t => t.vulnerability_index));
  const ex = sorted(tracts.map(t => Math.max(0, t.predicted_offset_f) * density(t)));
  const o02 = q(o, 0.02), o98 = q(o, 0.98);
  return { o02, o98, o33: q(o, 0.33), o66: q(o, 0.66), v33: q(v, 0.33), v66: q(v, 0.66), vmin: q(v, 0.02), vmax: q(v, 0.98),
    exmax: q(ex, 0.97) || 1, absmax: Math.max(Math.abs(o02), Math.abs(o98), 0.5) };
}

/** tract id -> the intervention touching it in this plan (wellness beats library beats truck, as in the planner). */
export function assignments(plan: Plan | null): Map<string, Kind> {
  const m = new Map<string, Kind>();
  if (!plan) return m;
  for (const kind of ['truck', 'lib', 'well'] as Kind[]) {
    for (const i of plan.items) {
      if (i.kind !== kind) continue;
      if (kind === 'lib') (i.served_tracts || []).forEach(t => m.set(t, 'lib'));
      else if (i.tract_geo_id) m.set(i.tract_geo_id, kind);
    }
  }
  return m;
}

export function lensFill(lens: LensKey, t: TractProps, s: LensStats, assigned: Map<string, Kind>, cutoff: number): string {
  switch (lens) {
    case 'temp': return heatRamp((t.predicted_offset_f - s.o02) / Math.max(s.o98 - s.o02, 0.1));
    case 'offset': return divRamp(0.5 + t.predicted_offset_f / (2 * s.absmax));
    case 'exposure': return heatRamp(Math.sqrt(Math.max(0, t.predicted_offset_f) * density(t) / s.exmax));
    case 'vuln': return purpleRamp((t.vulnerability_index - s.vmin) / Math.max(s.vmax - s.vmin, 0.01));
    case 'bivar': {
      const v = t.vulnerability_index < s.v33 ? 0 : t.vulnerability_index < s.v66 ? 1 : 2;
      const h = t.predicted_offset_f < s.o33 ? 0 : t.predicted_offset_f < s.o66 ? 1 : 2;
      return BIV[v][h];
    }
    default: {
      const a = assigned.get(t.tract_geo_id);
      if (a) return COLOR[a];
      return t.predicted_offset_f >= cutoff ? '#fce8dc' : '#ece8e0';
    }
  }
}

export type SiteLayer = 'lib' | 'police' | 'csc' | 'park' | 'senior' | 'college' | 'spray' | 'cps';
export const SITE_LAYERS: { k: SiteLayer; n: string; color: string }[] = [
  { k: 'lib', n: 'Libraries', color: '#4b4fd8' },
  { k: 'police', n: 'Police (24/7)', color: '#1f3b73' },
  { k: 'csc', n: 'Community svc ctr', color: '#1f6fb2' },
  { k: 'park', n: 'Park fieldhouse (A/C)', color: '#3c8a3f' },
  { k: 'senior', n: 'Senior centers', color: '#c77a12' },
  { k: 'college', n: 'City Colleges', color: '#7a3fa0' },
  { k: 'spray', n: 'Splash pads', color: '#33b5d6' },
  { k: 'cps', n: 'CPS high schools*', color: '#1e1c19' },
];
export function siteLayer(category: string): SiteLayer | null {
  const c = category.toLowerCase();
  if (c === 'library') return 'lib';
  if (c.startsWith('police')) return 'police';
  if (c.startsWith('community service')) return 'csc';
  if (c === 'park district facility') return 'park';
  if (c.includes('senior')) return 'senior';
  if (c.includes('college')) return 'college';
  if (c.includes('spray')) return 'spray';
  if (c.startsWith('cps')) return 'cps';
  return null;
}
