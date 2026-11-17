import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from './api';
import { Chat, type Msg } from './components/Chat';
import { LeftPanel } from './components/LeftPanel';
import { MapView } from './components/MapView';
import { RecPanel, type Tab } from './components/RecPanel';
import { Strip } from './components/Strip';
import { pct } from './format';
import type { LensKey, SiteLayer } from './lenses';
import type { Constraints, Day, Layers, Plan } from './types';

const QR_AFTER_REPLAN = ['undo', 'How many people are covered?', 'approve all'];

export default function App() {
  const [plan, setPlan] = useState<Plan | null>(null);
  const [layers, setLayers] = useState<Layers | null>(null);
  const [days, setDays] = useState<Day[]>([]);
  const [agentLabel, setAgentLabel] = useState('');
  const [lens, setLens] = useState<LensKey>('plan');
  const [siteLayers, setSiteLayers] = useState<Record<SiteLayer, boolean>>({ lib: true, police: true, csc: true, park: false, senior: false, college: false, spray: false, cps: false });
  const [tab, setTab] = useState<Tab>('all');
  const [selected, setSelected] = useState<string | null>(null);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const session = useRef<string | null>(null);

  const say = (m: Msg) => setMsgs(ms => [...ms, m]);
  const flash = (t: string) => { setToast(t); setTimeout(() => setToast(null), 2600); };

  useEffect(() => {
    (async () => {
      try {
        const [me, d, p] = await Promise.all([api.me(), api.days(), api.plan()]);
        setAgentLabel(me.agent === 'deployed' ? 'Agent Runtime' : 'local'); setDays(d.days); setPlan(p);
        const c = p.summary?.counts;
        say({ who: 'a', text: `Morning. Here's plan v${p.version} for ${p.day.label || p.day.weekday}${p.day.high_f != null ? ` (${p.day.high_f}°F)` : ''}: `
          + `${c?.well ?? 0} wellness teams, ${c?.truck ?? 0} trucks, ${c?.lib ?? 0} libraries with extended hours, reaching ${pct(p.summary?.share_of_hot_65_plus_reached)} of residents 65+ in hot tracts. `
          + 'Approve what looks right; tell me what changed.' });
      } catch (e) { setError(`Could not load the plan: ${(e as Error).message}`); }
      try { setLayers(await api.layers()); } catch (e) { setError(`Could not load the map: ${(e as Error).message}`); }
    })();
  }, []);

  const run = useCallback(async (f: () => Promise<Plan>, after?: (p: Plan) => void) => {
    setBusy(true);
    try { const p = await f(); setPlan(p); after?.(p); }
    catch (e) { flash((e as Error).message); }
    finally { setBusy(false); }
  }, []);

  const warnInChat = (p: Plan) => { if (p.warnings.length) say({ who: 'a', text: '', plan: p, qr: ['undo'] }); };

  const onAct = (action: 'approve' | 'unapprove' | 'approve_all' | 'skip', keys: string[] = [], kind?: string) =>
    run(() => api.action(action, keys, kind), p => {
      if (action === 'skip') say({ who: 'a', text: `Skipped that one and pulled in the next best. Plan is now v${p.version}.`, qr: ['undo'] });
      if (action === 'approve') flash('Approved');
      if (action === 'approve_all') flash('All shown recommendations approved');
    });

  const onConstraints = (c: Partial<Constraints>) => run(() => api.replan({ constraints: c }), warnInChat);
  const onDay = (d: Day) => run(() => api.replan({ day: d }), warnInChat);

  const send = async (raw: string) => {
    const text = raw.trim(); if (!text) return;
    say({ who: 'u', text });
    if (/^(undo|revert|go back)\b/i.test(text)) {
      return run(() => api.undo(), p => say({ who: 'a', text: `Reverted to the previous plan (now v${p.version}).` }));
    }
    if (/^approve all\b/i.test(text)) {
      return run(() => api.action('approve_all'), p => say({ who: 'a', text: `Approved everything. ${p.items.filter(i => i.approval).length} of ${p.items.length} now approved.` }));
    }
    setBusy(true);
    const idx = { current: -1 };
    setMsgs(ms => { idx.current = ms.length; return [...ms, { who: 'a', text: '', pending: 'Thinking…' }]; });
    const patch = (f: (m: Msg) => Msg) => setMsgs(ms => ms.map((m, i) => (i === idx.current ? f(m) : m)));
    try {
      for await (const ev of api.chat(text, session.current)) {
        if (ev.type === 'session') session.current = ev.session_id;
        else if (ev.type === 'tool') patch(m => ({ ...m, pending: `Working… (${ev.name.replace(/_/g, ' ')})` }));
        else if (ev.type === 'text') patch(m => ({ ...m, text: m.text ? `${m.text}\n${ev.text}` : ev.text }));
        else if (ev.type === 'plan') { setPlan(ev.plan); patch(m => ({ ...m, plan: ev.plan, qr: QR_AFTER_REPLAN })); }
        else if (ev.type === 'error') patch(m => ({ ...m, text: ev.message, error: true }));
      }
    } catch (e) {
      patch(m => ({ ...m, text: `The assistant is unavailable (${(e as Error).message}).`, error: true }));
    } finally {
      patch(m => ({ ...m, pending: undefined }));
      setBusy(false);
    }
  };

  const libName = plan?.items.find(i => i.kind === 'lib')?.name;
  const suggestions = ['Half the trucks are down (fuel shortage)', '2 drivers called in sick', ...(libName ? [`${libName} library has no power`] : []),
    'Rank by vulnerability first', 'We got 3 extra wellness teams', 'How many people are covered?'];

  return (
    <div className="app">
      <LeftPanel plan={plan} days={days} lens={lens} setLens={setLens} siteLayers={siteLayers} setSiteLayers={setSiteLayers} onConstraints={onConstraints} onDay={onDay} />
      <main className="center">
        <Strip plan={plan} />
        <MapView layers={layers} plan={plan} lens={lens} siteLayers={siteLayers} selected={selected} onPick={setSelected} />
      </main>
      <RecPanel plan={plan} tab={tab} setTab={setTab} selected={selected} onPick={setSelected} onAct={onAct} busy={busy}>
        <Chat msgs={msgs} onSend={send} suggestions={suggestions} busy={busy} agentLabel={agentLabel} />
      </RecPanel>
      {error && <div className="toast" style={{ display: 'block', background: '#b3261e' }}>{error}</div>}
      {toast && <div className="toast" style={{ display: 'block' }}>{toast}</div>}
    </div>
  );
}
