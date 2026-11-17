import { fmt, pct, sgn } from '../format';
import type { Plan } from '../types';

export function Strip({ plan }: { plan: Plan | null }) {
  const s = plan?.summary;
  const st = (v: React.ReactNode, l: string) => <div className="stat"><span className="v">{v}</span><span className="l">{l}</span></div>;
  return (
    <div className="strip" data-testid="strip">
      {st(s ? s.hot_tracts : '–', `hot tracts (≥ ${sgn(plan?.constraints.cutoff_f ?? 0, 2)})`)}
      {st(s ? fmt(s.residents_in_hot_tracts) : '–', 'residents in hot tracts')}
      {st(s ? pct(s.share_of_65_plus_in_hot_tracts) : '–', 'of residents 65+ live there')}
      {st(s ? pct(s.share_of_hot_65_plus_reached) : '–', 'of those 65+ reached by the plan')}
      {st(s ? <>{s.top50_heat_vs_vulnerability_overlap}<span style={{ fontSize: 12 }}> / 50</span></> : '–', 'hottest ∩ most vulnerable tracts')}
    </div>
  );
}
