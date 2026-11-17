import { useEffect, useRef, useState } from 'react';
import { EMOJI } from '../lenses';
import type { Kind, Plan } from '../types';

export interface Msg { who: 'u' | 'a'; text: string; plan?: Plan; pending?: string; error?: boolean; qr?: string[] }

export function DiffView({ plan }: { plan: Plan }) {
  const lines: { color: string; text: string }[] = [];
  for (const k of ['truck', 'well', 'lib'] as Kind[]) {
    const d = plan.diff?.[k]; if (!d) continue;
    const list = (a: { name: string }[]) => a.slice(0, 5).map(x => x.name).join(', ') + (a.length > 5 ? ` +${a.length - 5} more` : '');
    if (d.removed.length) lines.push({ color: '#b3261e', text: `− ${EMOJI[k]} ${list(d.removed)}` });
    if (d.added.length) lines.push({ color: '#13803f', text: `+ ${EMOJI[k]} ${list(d.added)}` });
  }
  return (
    <div className="diff" data-testid="plan-diff">
      <div className="note">Re-planned → <b>v{plan.version}</b>{plan.changes?.length ? ` · ${plan.changes.join(' · ')}` : ''}</div>
      {plan.warnings?.map((w, i) => <div key={`w${i}`} style={{ color: '#7a5a00' }}>⚠︎ {w.message}</div>)}
      {lines.length ? lines.map((l, i) => <div key={i} style={{ color: l.color }}>{l.text}</div>) : <div className="note">No sites changed.</div>}
    </div>
  );
}

export function Chat({ msgs, onSend, suggestions, busy, agentLabel }: {
  msgs: Msg[]; onSend: (t: string) => void; suggestions: string[]; busy: boolean; agentLabel: string;
}) {
  const [text, setText] = useState('');
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => { if (box.current) box.current.scrollTop = 1e6; }, [msgs]);
  return (
    <div className="chat">
      <div className="hd"><span className="kicker">Operator assistant</span><span className="note">ADK agent · {agentLabel}</span></div>
      <div className="msgs" ref={box} data-testid="chat-msgs">
        {msgs.map((m, i) => (
          <div key={i} className={`msg ${m.who}${m.error ? ' err' : ''}`}>
            {m.text && <div style={{ whiteSpace: 'pre-wrap' }}>{m.text}</div>}
            {m.pending && <div className="note">{m.pending}</div>}
            {m.plan && <DiffView plan={m.plan} />}
            {m.qr && <div className="qr">{m.qr.map(q => <button key={q} disabled={busy} onClick={() => onSend(q)}>{q}</button>)}</div>}
          </div>
        ))}
      </div>
      <div className="sugg">{suggestions.map(s => <button key={s} disabled={busy} onClick={() => onSend(s)}>{s}</button>)}</div>
      <form className="inrow" onSubmit={e => { e.preventDefault(); if (text.trim() && !busy) { onSend(text.trim()); setText(''); } }}>
        <input aria-label="message" autoComplete="off" placeholder="Tell me what changed, or ask why…" value={text} onChange={e => setText(e.target.value)} />
        <button className="btn" disabled={busy}>Send</button>
      </form>
    </div>
  );
}
