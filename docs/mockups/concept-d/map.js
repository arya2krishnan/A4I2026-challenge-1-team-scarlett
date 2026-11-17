// Shared helpers for the Chicago heat concept sketches. No external deps.
(function () {
  const H = {};
  H.load = async function () {
    const r = await fetch('data.json');
    const d = await r.json();
    d.tracts.forEach(t => { t.mock = true; });
    d.byId = new Map(d.tracts.map(t => [t.id, t]));
    // bounds
    let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
    d.city.forEach(ring => ring.forEach(([x, y]) => { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y); }));
    d.bounds = { x0, y0, x1, y1 };
    // tract area (km2) for densities
    d.tracts.forEach(t => { t.area = t.g.reduce((s, r) => s + Math.abs(ringArea(r)), 0); t.dens = t.pop / Math.max(t.area, 0.05); });
    computeDerived(d);
    H.data = d;
    return d;
  };
  function ringArea(r) { let a = 0; for (let i = 0, j = r.length - 1; i < r.length; j = i++) a += (r[j][0] + r[i][0]) * (r[j][1] - r[i][1]); return a / 2; }
  function dist(a, b) { return Math.hypot(a[0] - b[0], a[1] - b[1]); }
  H.dist = dist;
  function computeDerived(d) {
    d.tracts.forEach(t => {
      t.libKm = Math.min(...d.libs.map(l => dist(l.c, t.c)));
      t.lib = d.libs.reduce((b, l) => dist(l.c, t.c) < dist(b.c, t.c) ? l : b);
      t.coolKm = Math.min(...d.cool.map(l => dist(l.c, t.c)));
      t.n65 = Math.round(t.pop * t.p65 / 100); t.npov = Math.round(t.pop * t.pov / 100);
      t.nDis = Math.round(t.pop * t.dis / 100);
    });
    const P = d.tracts.reduce((s, t) => s + t.pop, 0);
    d.cityPov = d.tracts.reduce((s, t) => s + t.pov * t.pop, 0) / P;
    d.cityPop = P;
  }
  H.recompute = () => computeDerived(H.data);

  H.path = function (rings) { return rings.map(r => 'M' + r.map(p => p[0].toFixed(3) + ',' + p[1].toFixed(3)).join('L') + 'Z').join(''); };

  // ---------- pan / zoom for an <svg> ----------
  H.panZoom = function (svg, b, pad = 0.6) {
    let vb = { x: b.x0 - pad, y: b.y0 - pad, w: b.x1 - b.x0 + 2 * pad, h: b.y1 - b.y0 + 2 * pad };
    const home = { ...vb };
    const set = () => { svg.setAttribute('viewBox', `${vb.x} ${vb.y} ${vb.w} ${vb.h}`); svg.dispatchEvent(new CustomEvent('zoomed', { detail: vb })); };
    set();
    const pt = (e) => { const r = svg.getBoundingClientRect(); const s = Math.max(vb.w / r.width, vb.h / r.height); const ox = (r.width * s - vb.w) / 2, oy = (r.height * s - vb.h) / 2; return [vb.x - ox + (e.clientX - r.left) * s, vb.y - oy + (e.clientY - r.top) * s, s]; };
    svg.addEventListener('wheel', e => { e.preventDefault(); const [mx, my] = pt(e); const k = Math.exp(e.deltaY * 0.0015); const nw = Math.min(home.w * 1.2, Math.max(1.5, vb.w * k)); const kk = nw / vb.w; vb = { x: mx - (mx - vb.x) * kk, y: my - (my - vb.y) * kk, w: vb.w * kk, h: vb.h * kk }; set(); }, { passive: false });
    let drag = null;
    svg.addEventListener('pointerdown', e => { drag = { x: e.clientX, y: e.clientY, vb: { ...vb }, moved: false }; });
    window.addEventListener('pointermove', e => { if (!drag) return; const r = svg.getBoundingClientRect(); const s = Math.max(vb.w / r.width, vb.h / r.height); const dx = (e.clientX - drag.x) * s, dy = (e.clientY - drag.y) * s; if (Math.abs(e.clientX - drag.x) + Math.abs(e.clientY - drag.y) > 4) drag.moved = true; vb = { ...drag.vb, x: drag.vb.x - dx, y: drag.vb.y - dy }; set(); });
    window.addEventListener('pointerup', () => { if (drag) { svg._justDragged = drag.moved; setTimeout(() => svg._justDragged = false, 0); } drag = null; });
    return { home: () => { vb = { ...home }; set(); }, zoom: k => { const cx = vb.x + vb.w / 2, cy = vb.y + vb.h / 2; vb.w *= k; vb.h *= k; vb.x = cx - vb.w / 2; vb.y = cy - vb.h / 2; set(); }, get: () => vb };
  };

  // ---------- colour ----------
  function hex2rgb(h) { const n = parseInt(h.slice(1), 16); return [n >> 16 & 255, n >> 8 & 255, n & 255]; }
  H.ramp = function (stops) {
    const c = stops.map(hex2rgb);
    return v => { v = Math.max(0, Math.min(1, v)); const i = Math.min(c.length - 2, Math.floor(v * (c.length - 1))); const f = v * (c.length - 1) - i; const a = c[i], b = c[i + 1]; return `rgb(${Math.round(a[0] + (b[0] - a[0]) * f)},${Math.round(a[1] + (b[1] - a[1]) * f)},${Math.round(a[2] + (b[2] - a[2]) * f)})`; };
  };
  H.heatRamp = H.ramp(['#fbf3d5', '#fde3a0', '#fbb867', '#f2853f', '#dc5230', '#b02a2a', '#741326']);
  H.divRamp = H.ramp(['#2d5f9a', '#7fa8cf', '#e9e4da', '#f0a06a', '#c23b2b']);
  H.purpleRamp = H.ramp(['#f3f0f7', '#d4cbe6', '#a897cc', '#7a62ad', '#4b2f80']);
  H.tealRamp = H.ramp(['#eef6f4', '#c2e2db', '#7fc3b6', '#3b9c8c', '#16665b']);
  H.COL = { lib: '#4b4fd8', truck: '#0b8f86', well: '#cf2f6b', cool: '#1f6fb2', ink: '#1e1c19', muted: '#6f6a61' };

  // ---------- tooltip ----------
  H.tip = (() => { const el = document.createElement('div'); el.className = 'tip'; document.body.appendChild(el); return { show(html, e) { el.innerHTML = html; el.style.display = 'block'; const w = el.offsetWidth, h = el.offsetHeight; let x = e.clientX + 14, y = e.clientY + 14; if (x + w > innerWidth - 8) x = e.clientX - w - 14; if (y + h > innerHeight - 8) y = e.clientY - h - 14; el.style.left = x + 'px'; el.style.top = y + 'px'; }, hide() { el.style.display = 'none'; } }; })();

  H.fmt = n => n >= 1e6 ? (n / 1e6).toFixed(2) + 'M' : n >= 1e4 ? Math.round(n / 1e3) + 'k' : n >= 1e3 ? (n / 1e3).toFixed(1) + 'k' : String(Math.round(n));
  H.sgn = v => (v > 0 ? '+' : v < 0 ? '−' : '±') + Math.abs(v).toFixed(1) + '°';
  H.caName = t => H.data.cas[t.ca].n;

  // ---------- CSV drop-in ----------
  const MAP = { heat_offset: 'h', offset: 'h', pop: 'pop', poverty_pct: 'pov', age65_pct: 'p65', disability_pct: 'dis', no_vehicle_pct: 'nv', income_k: 'inc', sidewalk_severity: 'sev', missing_ramps_pct: 'ramp', canopy_pct: 'shade', transit_idx: 'tr', poverty_rate: 'pov', pct65: 'p65', no_vehicle_rate: 'nv', median_income: 'inc', score: 'sc', vuln_people: 'vp', hi: 'hi', tmax: 'tx', median_age: 'age', n: 'nr' };
  const SCALE = { poverty_rate: 100, pct65: 100, no_vehicle_rate: 100, median_income: 0.001 };
  H.CSV_COLUMNS = ['geoid', ...Object.keys(MAP)];
  H.loadCSV = function (text) {
    const lines = text.trim().split(/\r?\n/); const head = lines[0].split(',').map(s => s.trim().toLowerCase());
    const gi = head.findIndex(h => h === 'geoid' || h === 'geo_id' || h === 'tract');
    if (gi < 0) throw new Error('CSV needs a geoid column');
    let hit = 0; const cols = head.filter(h => MAP[h]);
    for (const ln of lines.slice(1)) {
      const v = ln.split(','); let id = (v[gi] || '').trim().replace(/^1400000US/, ''); const t = H.data.byId.get(id); if (!t) continue; hit++;
      head.forEach((h, i) => { if (MAP[h] && v[i] !== '' && !isNaN(+v[i])) t[MAP[h]] = +v[i] * (SCALE[h] || 1); });
      if (head.includes('offset') || head.includes('heat_offset')) t.m = 1;
      t.mock = false;
    }
    H.data.tracts.forEach(t => { t.dens = t.pop / Math.max(t.area, 0.05); });
    H.recompute();
    return { hit, cols };
  };
  H.csvButton = function (btn, onDone) {
    const inp = document.createElement('input'); inp.type = 'file'; inp.accept = '.csv,text/csv'; inp.style.display = 'none'; document.body.appendChild(inp);
    btn.addEventListener('click', () => inp.click());
    inp.addEventListener('change', async () => { const f = inp.files[0]; if (!f) return; try { const res = H.loadCSV(await f.text()); onDone(null, res); } catch (e) { onDone(e); } inp.value = ''; });
  };
  window.H = H;
})();
