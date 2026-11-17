import { useEffect, useRef } from 'react';
import { DAY_NAME, FEATURE_LABEL, fmt, pct, sgn, timeOf } from '../format';
import { COLOR, EMOJI } from '../lenses';
import type { Kind, Plan, PlanItem } from '../types';

export type Tab = 'all' | Kind;

function Why({ it }: { it: PlanItem }) {
  const chips: string[] = [];
  if (it.kind === 'lib') {
    chips.push(`${it.hours_today}${it.extend_to ? ` → extend to ${it.extend_to}` : ' (already late)'}`,
      `${it.served_tracts?.length ?? 0} hot tracts ≤ ${it.radius_km ?? 1.2} km`, `${fmt(it.served_population)} residents`, `${fmt(it.served_65_plus)} aged 65+`);
  } else {
    chips.push(`${sgn(it.predicted_offset_f)} hotter`, `${fmt(it.residents_65_plus)} aged 65+`, `poverty ${pct(it.poverty_rate)}`);
    if (it.km_to_indoor_cooling != null) chips.push(`indoor cooling ${Number(it.km_to_indoor_cooling).toFixed(1)} km${it.nearest_cooling_name ? ` (${it.nearest_cooling_name.slice(0, 22)})` : ''}`);
    (it.why || []).slice(0, 2).forEach(w => w.feature && chips.push(`${FEATURE_LABEL[w.feature] || w.feature} ${sgn(w.contribution_f, 1)}`));
  }
  return <div className="why">{chips.map((c, i) => <span key={i}>{c}</span>)}{it.kind === 'truck' && it.measured === false && <span style={{ background: '#fff0cc' }}>model prediction, never measured</span>}</div>;
}

function Num({ it }: { it: PlanItem }) {
  if (it.kind === 'truck') return <div className="num">{it.expected_air_temp_f != null ? `${it.expected_air_temp_f}°` : sgn(it.predicted_offset_f)}<small>{it.expected_air_temp_f != null ? 'expected air' : 'vs avg'}</small></div>;
  if (it.kind === 'well') return <div className="num">{fmt(it.residents_65_plus)}<small>aged 65+</small></div>;
  return <div className="num">{fmt(it.served_population)}<small>residents</small></div>;
}

export function RecPanel({ plan, tab, setTab, selected, onPick, onAct, busy, children }: {
  plan: Plan | null; tab: Tab; setTab: (t: Tab) => void; selected: string | null; onPick: (k: string) => void;
  onAct: (action: 'approve' | 'unapprove' | 'approve_all' | 'skip', keys?: string[], kind?: string) => void;
  busy: boolean; children: React.ReactNode;
}) {
  const items = plan?.items ?? [];
  const shown = items.filter(i => tab === 'all' || i.kind === tab);
  const ap = items.filter(i => i.approval).length;
  const listRef = useRef<HTMLDivElement>(null);
  useEffect(() => { if (selected) listRef.current?.querySelector(`[data-key="${CSS.escape(selected)}"]`)?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' }); }, [selected]);

  const copy = async () => {
    const rows = ['intervention,name,lat,lon,tract_or_branch,approved_by,approved_at,plan_version'];
    items.filter(i => i.approval).forEach(i => {
      const a = i.approval!;
      const kind = { well: 'wellness_check', truck: 'hydration_truck', lib: 'library_extended_hours' }[i.kind];
      rows.push(`${kind},"${i.name}",${i.latitude},${i.longitude},${i.kind === 'lib' ? 'branch' : i.tract_geo_id},${a.by},${a.at},${a.plan_version}`);
    });
    try { await navigator.clipboard.writeText(rows.join('\n')); } catch { /* clipboard blocked */ }
  };

  return (
    <aside className="rcol">
      <div className="rhead">
        <div className="row"><div className="kicker">Recommendations</div>
          <span className="ver" data-testid="plan-version">PLAN v{plan?.version ?? '–'} · {(plan?.day.label || DAY_NAME[plan?.day.weekday ?? ''] || '').toUpperCase()}</span></div>
        <div className="row" style={{ marginTop: 6 }}>
          <span style={{ fontWeight: 600 }} data-testid="approved-count">{ap} of {items.length} approved</span>
          <span className="row" style={{ gap: 6 }}>
            <button className="btn ghost" style={{ padding: '5px 10px' }} disabled={busy} onClick={() => onAct('approve_all', [], tab)}>Approve all</button>
            <button className="btn" style={{ padding: '5px 10px' }} onClick={copy}>Copy approved</button>
          </span>
        </div>
        <div className="progress"><i style={{ width: `${items.length ? (ap / items.length) * 100 : 0}%` }} /></div>
        {plan?.warnings.map((w, i) => <div className="warn" key={i}>⚠︎ {w.message}</div>)}
        <div className="tabs">{([['all', 'All'], ['well', '🩺'], ['truck', '🚚'], ['lib', '📚']] as [Tab, string][]).map(([k, l]) => (
          <button key={k} className={`tab${tab === k ? ' on' : ''}`} onClick={() => setTab(k)}>{l} <span className="c">{items.filter(i => k === 'all' || i.kind === k).length}</span></button>))}</div>
      </div>
      <div className={`list${busy ? ' busy' : ''}`} ref={listRef} data-testid="rec-list">
        {shown.map(it => (
          <div key={it.key} data-key={it.key} data-testid={`item-${it.key}`} className={`item${it.approval ? ' ok' : ''}${selected === it.key ? ' sel' : ''}`}
            style={{ borderLeftColor: COLOR[it.kind] }} onClick={() => onPick(it.key)}>
            <span className="rk">{it.rank}</span>
            <div>
              <div className="nm">{EMOJI[it.kind]} {it.name}</div>
              <div className="sub mono">{it.latitude.toFixed(4)}, {it.longitude.toFixed(4)}{it.kind !== 'lib' && it.tract_geo_id ? ` · tract ${it.tract_geo_id.slice(-6)}` : it.address ? ` · ${it.address}` : ''}</div>
              <Why it={it} />
              <div className="acts" onClick={e => e.stopPropagation()}>
                {it.approval
                  ? <span className="okbadge">✓ Approved {timeOf(it.approval.at)} · {it.approval.by.split('@')[0]} <button onClick={() => onAct('unapprove', [it.key])}>undo</button></span>
                  : <><button className="ap" onClick={() => onAct('approve', [it.key])}>✓ Approve</button>
                    <button className="sk" onClick={() => onAct('skip', [it.key])}>Skip, next best</button></>}
              </div>
            </div>
            <Num it={it} />
          </div>
        ))}
        {plan && !shown.length && <div className="note">Nothing to dispatch with these settings.</div>}
      </div>
      {children}
    </aside>
  );
}
