import { useEffect, useState } from 'react';
import { sgn } from '../format';
import { LENSES, SITE_LAYERS, type LensKey, type SiteLayer } from '../lenses';
import type { Constraints, Day, Plan } from '../types';

const RANK: { k: Constraints['ranking']; t: string }[] = [
  { k: 'balanced', t: 'Heat + vulnerability' }, { k: 'vulnerable', t: 'Vulnerable first' }, { k: 'heat', t: 'Heat only' },
];

export function LeftPanel({ plan, days, lens, setLens, siteLayers, setSiteLayers, onConstraints, onDay }: {
  plan: Plan | null; days: Day[]; lens: LensKey; setLens: (l: LensKey) => void;
  siteLayers: Record<SiteLayer, boolean>; setSiteLayers: (s: Record<SiteLayer, boolean>) => void;
  onConstraints: (c: Partial<Constraints>) => void; onDay: (d: Day) => void;
}) {
  const c = plan?.constraints;
  const [draft, setDraft] = useState<Partial<Constraints>>({});
  useEffect(() => setDraft({}), [plan?.version]);
  // debounce slider drags into one re-plan
  useEffect(() => {
    if (!Object.keys(draft).length) return;
    const t = setTimeout(() => onConstraints(draft), 450);
    return () => clearTimeout(t);
  }, [draft]); // eslint-disable-line react-hooks/exhaustive-deps
  const val = <K extends keyof Constraints>(k: K): Constraints[K] | undefined => (draft[k] ?? c?.[k]) as Constraints[K] | undefined;
  const [hiDraft, setHiDraft] = useState('');
  const cur = plan?.day;
  const hi = cur?.high_f;

  return (
    <aside className="panel">
      <div className="kicker">Heat Dispatch Console · Chicago</div>
      <h2 style={{ fontSize: 21, marginTop: 6 }}>Plan, check, approve</h2>
      <p className="note" style={{ marginTop: 5 }}>Recommendations come from the BigQuery ML heat model and ACS. Approve what you agree with; tell the assistant what changed.</p>

      <div className="box"><h4>Day <span className="note">{hi != null ? <>{hi}°F {hi >= 95 ? <b style={{ color: '#c23b2b' }}>· activate</b> : '· preview'}</> : 'no forecast'}</span></h4>
        <div className="chips">{days.map(d => (
          <button key={d.date || d.weekday} className={`chip${cur?.date === d.date ? ' on' : ''}`} onClick={() => onDay(d)} title={d.short_forecast || ''}>
            {d.label || d.weekday} {d.high_f != null && <b>{d.high_f}°</b>}
          </button>))}</div>
        <form className="dayhi" onSubmit={e => { e.preventDefault(); const v = parseFloat(hiDraft); if (cur && Number.isFinite(v)) { onDay({ ...cur, high_f: v }); setHiDraft(''); } }}>
          <span className="note">Scenario high</span><input aria-label="scenario high" inputMode="decimal" placeholder={hi != null ? String(hi) : '°F'} value={hiDraft} onChange={e => setHiDraft(e.target.value)} />
          <button className="btn ghost" style={{ padding: '3px 8px' }}>Set</button>
        </form>
      </div>

      <div className="box"><h4>Map lens</h4>
        <div className="lens">{LENSES.map(l => (
          <button key={l.k} className={lens === l.k ? 'on' : ''} onClick={() => setLens(l.k)}>
            <span className="sw" style={{ background: l.sw }} /><span>{l.t}<small>{l.d}</small></span>
          </button>))}</div>
      </div>

      <div className="box"><h4>Sites <span className="note">real · City data</span></h4>
        <div className="layers">{SITE_LAYERS.map(l => (
          <label key={l.k}><input type="checkbox" checked={siteLayers[l.k]} onChange={e => setSiteLayers({ ...siteLayers, [l.k]: e.target.checked })} />
            <span className="ico" style={{ background: l.color, borderRadius: 3 }} />{l.n}</label>))}
          <span className="note" style={{ marginTop: 3 }}>*CPS high schools are candidate sites only, not in today's cooling plan.</span>
        </div>
      </div>

      <details className="box" open><summary>Resources today</summary>
        <div className="res">
          {([['trucks', '🚚', 'trucks'], ['wellness_teams', '🩺', 'wellness teams'], ['libraries', '📚', 'libraries']] as const).map(([k, e, label]) => (
            <ResRow key={k} emoji={e} label={label} max={plan?.limits?.[k] ?? 25} value={(val(k) as number) ?? 0} onChange={v => setDraft({ ...draft, [k]: v })} />
          ))}
        </div>
        <div className="note" style={{ marginTop: 4 }}>Trucks · wellness-check teams · library branches extending hours</div>
      </details>

      <details className="box" open><summary>Rules</summary>
        <div className="slider"><div className="row"><span>Hot: modelled offset at least</span><b>{sgn((val('cutoff_f') as number) ?? 0, 2)}</b></div>
          <input type="range" aria-label="hot cutoff" min={-1} max={2.5} step={0.25} value={(val('cutoff_f') as number) ?? 0} onChange={e => setDraft({ ...draft, cutoff_f: +e.target.value })} /></div>
        <div className="note" style={{ margin: '-2px 0 6px' }}>°F vs the city average, BigQuery ML prediction (one volunteer-driven afternoon: a ranking signal, not a thermometer)</div>
        <div className="kicker" style={{ margin: '6px 0 4px' }}>Rank by</div>
        <div className="seg2" style={{ gridTemplateColumns: '1fr 1fr 1fr' }}>{RANK.map(r => (
          <button key={r.k} className={val('ranking') === r.k ? 'on' : ''} onClick={() => onConstraints({ ranking: r.k })}>{r.t}</button>))}</div>
        {!!c?.closed_sites.length && <>
          <div className="kicker" style={{ margin: '10px 0 2px' }}>Closed today</div>
          <div className="closed">{c.closed_sites.map(s => (
            <button key={s} title="Reopen" onClick={() => onConstraints({ closed_sites: c.closed_sites.filter(x => x !== s) })}>{s} ×</button>))}</div>
        </>}
      </details>
    </aside>
  );
}

function ResRow({ emoji, label, max, value, onChange }: { emoji: string; label: string; max: number; value: number; onChange: (v: number) => void }) {
  return <>
    <span>{emoji}</span>
    <input type="range" aria-label={label} min={0} max={max} value={value} onChange={e => onChange(+e.target.value)} />
    <b>{value}</b>
  </>;
}
