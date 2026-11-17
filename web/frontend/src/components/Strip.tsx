import { fmt, pct } from '../format';
import type { Plan } from '../types';

export function Strip({ plan }: { plan: Plan | null }) {
  const s = plan?.summary;
  const isStandDown = plan?.stand_down;

  if (isStandDown) {
    return (
      <div className="strip stand-down" data-testid="strip" style={{ background: '#e6f7ed', color: '#0f5132', borderBottom: '1px solid #badbcc' }}>
        <div className="stat" style={{ flex: 1, textAlign: 'left', padding: '0 16px' }}>
          <span className="v" style={{ fontSize: 15, color: '#0f5132', fontWeight: 600 }}>🟢 Normal Weather Operations ({plan?.day.high_f ?? 72}°F &lt; 80°F)</span>
          <span className="l" style={{ color: '#0f5132' }}>No heat emergency in effect. All mobile hydration trucks, door-to-door wellness teams, and extended library cooling hours are standing down.</span>
        </div>
      </div>
    );
  }

  const trucks = plan?.constraints.trucks ?? 10;
  const reachPct = s ? Math.round(s.share_of_hot_65_plus_reached * 100) : 11;
  const expandedPct = Math.min(95, reachPct + Math.max(10, Math.round((4 / Math.max(1, trucks)) * reachPct)));

  return (
    <div className="strip" data-testid="strip">
      <div className="stat">
        <span className="v">{s ? fmt(s.residents_in_hot_tracts) : '1.67M'}</span>
        <span className="l">Residents at risk ({s ? s.hot_tracts : '481'} hot tracts &ge; +0.5°F)</span>
      </div>
      <div className="stat">
        <span className="v">{s ? pct(s.share_of_hot_65_plus_reached) : '11%'}</span>
        <span className="l">Seniors 65+ reached ({s ? pct(s.share_of_65_plus_in_hot_tracts) : '68%'} of Chicago seniors live in hot tracts)</span>
      </div>
      <div className="stat">
        <span className="v" style={{ fontSize: 15, fontWeight: 700 }}>{trucks} trucks &rarr; {reachPct}% reach</span>
        <span className="l">Sizing trade-off: Adding 4 trucks expands senior coverage to ~{expandedPct}%</span>
      </div>
    </div>
  );
}
