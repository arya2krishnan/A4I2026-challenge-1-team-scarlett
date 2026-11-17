import { sgn } from '../format';
import { BIV, COLOR, SITE_LAYERS, divRamp, heatRamp, purpleRamp, type LensKey, type LensStats, type SiteLayer } from '../lenses';
import type { Plan } from '../types';

const Bar = ({ r }: { r: (v: number) => string }) => (
  <div className="bar" style={{ background: `linear-gradient(90deg,${[0, 0.25, 0.5, 0.75, 1].map(r).join(',')})` }} />
);

export function Legend({ lens, plan, stats, siteLayers }: { lens: LensKey; plan: Plan | null; stats: LensStats; siteLayers: Record<SiteLayer, boolean> }) {
  const hi = plan?.day.high_f;
  const dayName = plan?.day.label || plan?.day.weekday || '';
  const on = SITE_LAYERS.filter(l => siteLayers[l.k]);
  return (
    <div className="legend" data-testid="legend">
      {lens === 'plan' && <>
        <div className="kicker">Dispatch plan · {dayName}</div>
        {(['well', 'truck', 'lib'] as const).map(k => (
          <div className="li" key={k}><span className="sq" style={{ background: COLOR[k] }} />{{ well: '🩺 Wellness checks', truck: '🚚 Hydration truck', lib: '📚 Library hours' }[k]}</div>
        ))}
        <div className="li"><span className="sq" style={{ background: 'repeating-linear-gradient(45deg,#f6d9c4 0 3px,#d98a5f 3px 4px)' }} />Hot (≥ {sgn(plan?.constraints.cutoff_f ?? 0, 2)}), not covered</div>
        <div className="li"><span className="sq" style={{ background: '#ece8e0' }} />Below cutoff</div>
      </>}
      {lens === 'temp' && <>
        <div className="kicker">Street-level high · {dayName} {hi != null ? `(${hi}°F forecast)` : '(no forecast)'}</div>
        <Bar r={heatRamp} />
        <div className="ticks">{hi != null
          ? <><span>{Math.round(hi + stats.o02)}°</span><span>{Math.round(hi + (stats.o02 + stats.o98) / 2)}°</span><span>{Math.round(hi + stats.o98)}°F</span></>
          : <><span>{sgn(stats.o02)}</span><span /><span>{sgn(stats.o98)}</span></>}</div>
      </>}
      {lens === 'offset' && <><div className="kicker">vs. city average (BigQuery ML)</div><Bar r={divRamp} />
        <div className="ticks"><span>{sgn(-stats.absmax)}</span><span>0</span><span>{sgn(stats.absmax)}</span></div></>}
      {lens === 'exposure' && <><div className="kicker">Residents/km² × °F above avg</div><Bar r={heatRamp} /><div className="ticks"><span>none</span><span /><span>highest</span></div></>}
      {lens === 'vuln' && <><div className="kicker">Vulnerability index (ACS)</div><Bar r={purpleRamp} /><div className="ticks"><span>lower</span><span /><span>higher</span></div></>}
      {lens === 'bivar' && <><div className="kicker">Heat × vulnerability</div>
        <div className="row" style={{ gap: 10, alignItems: 'flex-end' }}>
          <div><div className="bv">{[2, 1, 0].map(v => [0, 1, 2].map(x => <i key={`${v}${x}`} style={{ background: BIV[v][x] }} />))}</div><div className="note">heat →</div></div>
          <div className="note">↑ vulnerability<br />Top-right: hot <i>and</i> vulnerable</div>
        </div></>}
      {lens !== 'plan' && <div className="note" style={{ marginTop: 6 }}>Outlines + pins = today's dispatch</div>}
      {on.length > 0 && <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2px 10px', marginTop: 8, fontSize: 11.5, whiteSpace: 'nowrap' }}>
        {on.map(l => <span className="row" style={{ gap: 5 }} key={l.k}><span className="ico" style={{ background: l.color, borderRadius: 3 }} />{l.n}</span>)}
      </div>}
    </div>
  );
}
