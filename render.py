"""HTML renderer for the Forex Rotation dashboard (heat map + RRG, 4H and Daily).

Color, by job:
  - Heat map and strength bars are DIVERGING (polarity around 0%): blue for up,
    red for down, a neutral gray midpoint, interpolated in OKLab so each arm is
    monotone in lightness. Poles validated with the dataviz validator: CVD
    separation dE 21.6 light / 19.2 dark. Every cell also prints its signed
    value, so color is never the only cue.
  - RRG marks share ONE color. Quadrant is carried by position and labelled
    regions; base/quote side in a filtered pairs view is carried by SHAPE
    (hollow = the chosen currency is the quote leg), not by color.
"""
import json

CSS = r"""
:root{
  --plane:#f9f9f7; --surface-1:#fcfcfb;
  --text-primary:#0b0b0b; --text-secondary:#52514e; --muted:#898781;
  --grid:#e1e0d9; --axis:#c3c2b7; --border:rgba(11,11,11,0.10); --chip:#efeee9;
  --mark:#2a78d6; --mark-tail:#86b6ef;
  --div-pos:#2a78d6; --div-neg:#e34948; --div-mid:#f0efec;
  --q-lead:rgba(12,163,12,0.07); --q-weak:rgba(250,178,25,0.09);
  --q-lag:rgba(208,59,59,0.07); --q-imp:rgba(42,120,214,0.07);
  --warn:#8a5a10; --warn-bg:rgba(250,178,25,0.13);
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --plane:#0d0d0d; --surface-1:#1a1a19;
    --text-primary:#ffffff; --text-secondary:#c3c2b7; --muted:#898781;
    --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,0.10); --chip:#242422;
    --mark:#3987e5; --mark-tail:#1c5cab;
    --div-pos:#3987e5; --div-neg:#e66767; --div-mid:#383835;
    --q-lead:rgba(12,163,12,0.075); --q-weak:rgba(250,178,25,0.065);
    --q-lag:rgba(208,59,59,0.075); --q-imp:rgba(57,135,229,0.08);
    --warn:#f0c266; --warn-bg:rgba(250,178,25,0.10);
  }
}
:root[data-theme="dark"]{
  --plane:#0d0d0d; --surface-1:#1a1a19;
  --text-primary:#ffffff; --text-secondary:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,0.10); --chip:#242422;
  --mark:#3987e5; --mark-tail:#1c5cab;
  --div-pos:#3987e5; --div-neg:#e66767; --div-mid:#383835;
  --q-lead:rgba(12,163,12,0.075); --q-weak:rgba(250,178,25,0.065);
  --q-lag:rgba(208,59,59,0.075); --q-imp:rgba(57,135,229,0.08);
  --warn:#f0c266; --warn-bg:rgba(250,178,25,0.10);
}
*{box-sizing:border-box}
body{font-family:system-ui,-apple-system,"Segoe UI",sans-serif; color:var(--text-primary);
  background:var(--plane); max-width:1180px; margin:0 auto; padding:28px 16px 64px; line-height:1.5}
.eyebrow{font-size:.72rem; letter-spacing:.09em; text-transform:uppercase; color:var(--muted); margin:0 0 6px}
h1{font-size:1.75rem; margin:0 0 6px; letter-spacing:-0.02em}
h2{font-size:1.05rem; margin:0 0 4px}
.sub{color:var(--text-secondary); margin:0 0 4px; font-size:.95rem}
.meta{color:var(--muted); font-size:.8rem; margin:0 0 20px}
.card{background:var(--surface-1); border:1px solid var(--border); border-radius:12px; padding:16px; margin-bottom:18px}
.bar{display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin:0 0 14px}
.seg{display:inline-flex; padding:3px; gap:3px; background:var(--chip); border-radius:10px}
.seg button{font:inherit; font-size:.85rem; font-weight:600; padding:6px 16px; border-radius:7px;
  cursor:pointer; background:transparent; color:var(--text-secondary); border:0}
.seg button[aria-selected="true"]{background:var(--surface-1); color:var(--text-primary); box-shadow:0 1px 3px rgba(0,0,0,.14)}
#tfseg button[aria-selected="true"]{background:var(--mark); color:#fff}
.status{font-size:.8rem; color:var(--muted)}
.chip{font:inherit; font-size:.78rem; padding:5px 11px; border-radius:999px; cursor:pointer;
  background:var(--chip); color:var(--text-secondary); border:1px solid transparent}
.chip[aria-pressed="false"]{opacity:.45}
.chip[aria-pressed="true"].sel{background:var(--mark); color:#fff}
.chip .n{opacity:.65; margin-left:5px; font-variant-numeric:tabular-nums}
.hint{font-size:.8rem; color:var(--text-secondary); margin:0 0 12px}
.heatwrap{display:grid; grid-template-columns:minmax(0,1fr) 300px; gap:22px; align-items:start}
@media (max-width:900px){ .heatwrap{grid-template-columns:1fr} }
.scroll{overflow-x:auto}
table.heat{border-collapse:separate; border-spacing:2px; font-size:.8rem; min-width:520px; width:100%}
table.heat th{font-weight:600; color:var(--text-secondary); padding:6px 4px; text-align:center}
table.heat th.row{text-align:right; padding-right:10px}
table.heat td{text-align:center; padding:9px 4px; border-radius:4px; font-variant-numeric:tabular-nums; cursor:default}
table.heat td.diag{background:transparent; color:var(--muted)}
.strength .row{display:grid; grid-template-columns:40px 1fr 62px; align-items:center; gap:8px; margin:5px 0; font-size:.8rem}
.strength .lab{font-weight:600}
.strength .val{text-align:right; font-variant-numeric:tabular-nums; color:var(--text-secondary)}
.strength .track{position:relative; height:16px}
.strength .zero{position:absolute; left:50%; top:-3px; bottom:-3px; width:1px; background:var(--axis)}
.strength .fill{position:absolute; top:2px; bottom:2px}
.strength .fill.pos{left:50%; border-radius:0 4px 4px 0; background:var(--div-pos)}
.strength .fill.neg{right:50%; border-radius:4px 0 0 4px; background:var(--div-neg)}
.legend{display:flex; gap:16px; flex-wrap:wrap; font-size:.76rem; color:var(--text-secondary); margin-top:10px; align-items:center}
.legend i{display:inline-block; width:10px; height:10px; border-radius:50%; background:var(--mark); margin-right:5px; vertical-align:-1px}
.legend i.hollow{background:transparent; border:1.8px solid var(--mark)}
.legend .tl{display:inline-block; width:16px; height:2px; background:var(--mark-tail); margin-right:5px; vertical-align:4px}
.legend .ramp{display:inline-block; width:120px; height:10px; border-radius:3px; vertical-align:-1px; margin:0 6px}
.filters{display:flex; gap:6px; flex-wrap:wrap; align-items:center; margin-bottom:12px}
.sidenote{background:var(--warn-bg); color:var(--warn); border-radius:8px; padding:8px 12px; font-size:.8rem; margin-bottom:12px}
.layout{display:grid; grid-template-columns:minmax(0,560px) minmax(0,1fr); gap:20px; align-items:start}
@media (max-width:940px){ .layout{grid-template-columns:1fr} }
.plotwrap{position:relative}
svg{width:100%; height:auto; display:block; overflow:visible}
.qlabel{font-size:11px; fill:var(--muted); letter-spacing:.05em; text-transform:uppercase}
.axlabel{font-size:10px; fill:var(--muted); font-variant-numeric:tabular-nums}
.mlabel{font-size:10.5px; fill:var(--text-secondary); font-weight:600}
.axtitle{font-size:11px; fill:var(--text-secondary)}
.tip{position:fixed; pointer-events:none; opacity:0; transition:opacity .1s; z-index:9;
  background:var(--text-primary); color:var(--plane); font-size:.75rem; padding:6px 9px; border-radius:7px; white-space:nowrap}
.tablewrap{max-height:560px; overflow:auto}
table.list{width:100%; border-collapse:collapse; font-size:.8rem}
table.list th, table.list td{text-align:right; padding:6px 7px; border-bottom:1px solid var(--border); white-space:nowrap}
table.list th:first-child, table.list td:first-child{text-align:left}
table.list th{position:sticky; top:0; background:var(--surface-1); cursor:pointer; font-weight:600; color:var(--text-secondary)}
table.list td.q{text-align:left; color:var(--text-secondary)}
td.num{font-variant-numeric:tabular-nums}
.note{font-size:.78rem; color:var(--text-secondary); margin-top:8px; line-height:1.65}
.note strong{color:var(--text-primary)}
"""

JS = r"""
const $ = s => document.querySelector(s);
const NS = 'http://www.w3.org/2000/svg';
const S = 560, M = {t:28, r:32, b:44, l:50};
const QS = ['Leading','Weakening','Lagging','Improving'];
const state = {tf:0, per:0, mode:'ccy', ccy:null, q:new Set(QS), labels:true, sort:'t', dir:1};
const view = () => VIEWS[state.tf];
const fmt = v => (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(2);
const tip = $('#tip');
function showTip(html, e){ tip.innerHTML = html; tip.style.opacity = 1; moveTip(e); }
function moveTip(e){ tip.style.left = (e.clientX + 14) + 'px'; tip.style.top = (e.clientY + 12) + 'px'; }
function hideTip(){ tip.style.opacity = 0; }

/* ---------- OKLab interpolation for the diverging ramp ---------- */
const lin = c => c <= 0.04045 ? c/12.92 : Math.pow((c+0.055)/1.055, 2.4);
const gam = c => c <= 0.0031308 ? 12.92*c : 1.055*Math.pow(c, 1/2.4) - 0.055;
function hex(h){ h = h.trim().replace('#',''); if (h.length === 3) h = h.split('').map(c=>c+c).join('');
  const n = parseInt(h,16); return [(n>>16)&255,(n>>8)&255,n&255].map(v=>v/255); }
function toLab(rgb){ const [r,g,b] = rgb.map(lin);
  const l = Math.cbrt(0.4122214708*r+0.5363325363*g+0.0514459929*b),
        m = Math.cbrt(0.2119034982*r+0.6806995451*g+0.1073969566*b),
        s = Math.cbrt(0.0883024619*r+0.2817188376*g+0.6299787005*b);
  return [0.2104542553*l+0.7936177850*m-0.0040720468*s,
          1.9779984951*l-2.4285922050*m+0.4505937099*s,
          0.0259040371*l+0.7827717662*m-0.8086757660*s]; }
function fromLab([L,a,b]){ const l=(L+0.3963377774*a+0.2158037573*b)**3,
  m=(L-0.1055613458*a-0.0638541728*b)**3, s=(L-0.0894841775*a-1.2914855480*b)**3;
  return [4.0767416621*l-3.3077115913*m+0.2309699292*s,
          -1.2684380046*l+2.6097574011*m-0.3413193965*s,
          -0.0041960863*l-0.7034186147*m+1.7076147010*s].map(v=>Math.min(1,Math.max(0,gam(v)))); }
function tokens(){ const cs = getComputedStyle(document.documentElement);
  return {pos:toLab(hex(cs.getPropertyValue('--div-pos'))), neg:toLab(hex(cs.getPropertyValue('--div-neg'))),
          mid:toLab(hex(cs.getPropertyValue('--div-mid')))}; }
function divColor(v, max, T){
  const t = Math.min(1, Math.abs(v)/(max || 1)), pole = v >= 0 ? T.pos : T.neg;
  const rgb = fromLab(T.mid.map((m,i) => m + (pole[i]-m)*t));
  const Y = 0.2126*lin(rgb[0]) + 0.7152*lin(rgb[1]) + 0.0722*lin(rgb[2]);
  const ink = (1.05/(Y+0.05)) > ((Y+0.05)/0.0535) ? '#ffffff' : '#0b0b0b';
  return {bg:'rgb(' + rgb.map(c=>Math.round(c*255)).join(',') + ')', ink};
}

/* ---------------------------- heat map ---------------------------- */
function heat(){
  const v = view(), h = v.heat[state.per], T = tokens();
  $('#heatdesc').textContent = `% change over the ${h.desc}. Read across: each cell is the row currency priced in the column currency.`;
  let max = 0;
  for (const a of CCY) for (const b of CCY) if (a !== b) max = Math.max(max, Math.abs(h.matrix[a][b]));
  let html = '<thead><tr><th></th>' + CCY.map(c => `<th scope="col">${c}</th>`).join('') + '</tr></thead><tbody>';
  for (const a of CCY){
    html += `<tr><th scope="row" class="row">${a}</th>`;
    for (const b of CCY){
      if (a === b){ html += '<td class="diag">&middot;</td>'; continue; }
      const val = h.matrix[a][b], c = divColor(val, max, T);
      html += `<td style="background:${c.bg};color:${c.ink}" data-a="${a}" data-b="${b}" data-v="${val}">${fmt(val)}</td>`;
    }
    html += '</tr>';
  }
  $('#heat').innerHTML = html + '</tbody>';
  $('#heat').querySelectorAll('td[data-a]').forEach(td => {
    td.onmousemove = e => showTip(`<strong>${td.dataset.a}/${td.dataset.b}</strong> ${fmt(+td.dataset.v)}%<br>` +
      `${td.dataset.a} ${+td.dataset.v >= 0 ? 'rose' : 'fell'} against ${td.dataset.b} over the ${h.desc}`, e);
    td.onmouseleave = hideTip;
  });
  const st = Object.entries(h.strength).sort((x,y) => y[1]-x[1]);
  const smax = Math.max(...st.map(([,x]) => Math.abs(x))) || 1;
  $('#strength').innerHTML = st.map(([c,x]) =>
    `<div class="row"><span class="lab">${c}</span><span class="track"><span class="zero"></span>` +
    `<span class="fill ${x >= 0 ? 'pos' : 'neg'}" style="width:${(Math.abs(x)/smax*50).toFixed(2)}%"></span></span>` +
    `<span class="val">${fmt(x)}%</span></div>`).join('');
  const lo = divColor(-1,1,T).bg, mid = divColor(0,1,T).bg, hi = divColor(1,1,T).bg;
  $('#ramp').style.background = `linear-gradient(90deg, ${lo}, ${mid}, ${hi})`;
  $('#rampmax').textContent = max.toFixed(2) + '%';
}

/* ------------------------------ RRG ------------------------------- */
const el = (n,a) => { const e = document.createElementNS(NS,n); for (const k in a) e.setAttribute(k,a[k]); return e; };
function universe(){
  const v = view();
  if (state.mode === 'ccy') return v.ccy.map(p => ({...p, side:''}));
  let pts = v.pairs.map(p => ({...p, side:''}));
  if (state.ccy) pts = pts.filter(p => p.base === state.ccy || p.quote === state.ccy)
                         .map(p => ({...p, side: p.base === state.ccy ? 'base' : 'quote'}));
  return pts;
}
const visible = () => universe().filter(r => state.q.has(r.q));
function domain(pts){ let lo = 100, hi = 100;
  for (const r of pts) for (const [a,b] of r.tail){ lo = Math.min(lo,a,b); hi = Math.max(hi,a,b); }
  const half = Math.max(hi-100, 100-lo)*1.1 || 2; return {lo:100-half, hi:100+half}; }

function draw(){
  const svg = $('#plot'); svg.textContent = '';
  const all = universe(), rows = visible(), D = domain(all);
  const px = v => M.l + (v-D.lo)/(D.hi-D.lo)*(S-M.l-M.r);
  const py = v => S - M.b - (v-D.lo)/(D.hi-D.lo)*(S-M.t-M.b);
  const L = M.l, R = S-M.r, T = M.t, B = S-M.b, x0 = px(100), y0 = py(100);
  for (const [x,y,w,h,f] of [[x0,T,R-x0,y0-T,'--q-lead'],[x0,y0,R-x0,B-y0,'--q-weak'],[L,y0,x0-L,B-y0,'--q-lag'],[L,T,x0-L,y0-T,'--q-imp']])
    svg.appendChild(el('rect',{x,y,width:Math.max(0,w),height:Math.max(0,h),fill:`var(${f})`}));
  for (const [tx,ty,an,tt] of [[R-6,T+14,'end','Leading'],[R-6,B-8,'end','Weakening'],[L+6,B-8,'start','Lagging'],[L+6,T+14,'start','Improving']]){
    const t = el('text',{x:tx,y:ty,class:'qlabel','text-anchor':an}); t.textContent = tt; svg.appendChild(t); }
  const span = D.hi-D.lo, step = span > 12 ? 4 : span > 6 ? 2 : span > 3 ? 1 : 0.5;
  for (let v = Math.ceil(D.lo/step)*step; v <= D.hi; v += step){
    svg.appendChild(el('line',{x1:px(v),y1:T,x2:px(v),y2:B,stroke:'var(--grid)','stroke-width':1}));
    svg.appendChild(el('line',{x1:L,y1:py(v),x2:R,y2:py(v),stroke:'var(--grid)','stroke-width':1}));
    const lab = +v.toFixed(1);
    const a = el('text',{x:px(v),y:B+16,class:'axlabel','text-anchor':'middle'}); a.textContent = lab; svg.appendChild(a);
    const b = el('text',{x:L-8,y:py(v)+4,class:'axlabel','text-anchor':'end'}); b.textContent = lab; svg.appendChild(b);
  }
  svg.appendChild(el('line',{x1:x0,y1:T,x2:x0,y2:B,stroke:'var(--axis)','stroke-width':1.5}));
  svg.appendChild(el('line',{x1:L,y1:y0,x2:R,y2:y0,stroke:'var(--axis)','stroke-width':1.5}));
  const xt = el('text',{x:(L+R)/2,y:S-8,class:'axtitle','text-anchor':'middle'});
  xt.textContent = state.mode === 'ccy' ? 'RS-Ratio  (currency index vs the G10 basket)' : 'RS-Ratio  (pair vs its own 60-bar norm)';
  svg.appendChild(xt);
  const yt = el('text',{x:12,y:(T+B)/2,class:'axtitle','text-anchor':'middle',transform:`rotate(-90 12 ${(T+B)/2})`});
  yt.textContent = 'RS-Momentum'; svg.appendChild(yt);
  const per = view().periods;
  for (const r of rows){
    svg.appendChild(el('polyline',{points:r.tail.map(([a,b]) => `${px(a)},${py(b)}`).join(' '),
      fill:'none',stroke:'var(--mark-tail)','stroke-width':2,'stroke-linecap':'round','stroke-linejoin':'round'}));
    const hollow = r.side === 'quote';
    const dot = el('circle', hollow
      ? {cx:px(r.x),cy:py(r.y),r:4.3,fill:'var(--surface-1)',stroke:'var(--mark)','stroke-width':2}
      : {cx:px(r.x),cy:py(r.y),r:4.5,fill:'var(--mark)',stroke:'var(--surface-1)','stroke-width':2});
    const hit = el('circle',{cx:px(r.x),cy:py(r.y),r:11,fill:'transparent'});
    hit.onmousemove = e => showTip(`<strong>${r.t}</strong> &middot; ${r.q}<br>${r.n}<br>` +
      `RS-Ratio ${r.x.toFixed(2)} &middot; Mom ${r.y.toFixed(2)}<br>` +
      per.map((p,i) => `${p.key} ${fmt(r.chg[i])}%`).join(' &middot; ') +
      (r.side ? `<br><span style="opacity:.75">${state.ccy} is the ${r.side} leg</span>` : ''), e);
    hit.onmouseleave = hideTip;
    svg.appendChild(dot); svg.appendChild(hit);
    if (state.labels){ const lb = el('text',{x:px(r.x)+8,y:py(r.y)-7,class:'mlabel'}); lb.textContent = r.t; svg.appendChild(lb); }
  }
}

function table(){
  const per = view().periods, sided = state.mode === 'pairs' && state.ccy;
  $('#thead').innerHTML = '<tr><th data-k="t">Name</th>' + (sided ? '<th data-k="side">Side</th>' : '') +
    '<th data-k="q">Quadrant</th><th data-k="x">RS-Ratio</th><th data-k="y">RS-Mom</th>' +
    '<th data-k="dx">&Delta; Ratio</th><th data-k="dy">&Delta; Mom</th>' +
    per.map((p,i) => `<th data-k="c${i}">${p.key} %</th>`).join('') + '</tr>';
  $('#thead').querySelectorAll('th').forEach(th => th.onclick = () => {
    state.dir = state.sort === th.dataset.k ? -state.dir : 1; state.sort = th.dataset.k; table(); });
  const key = r => state.sort.startsWith('c') ? r.chg[+state.sort.slice(1)] : r[state.sort];
  const rows = visible().slice().sort((a,b) => { const va = key(a), vb = key(b);
    return (typeof va === 'string' ? va.localeCompare(vb) : va - vb) * state.dir; });
  $('#tbody').innerHTML = rows.map(r => `<tr title="${r.n}"><td><strong>${r.t}</strong></td>` +
    (sided ? `<td class="q">${r.side}</td>` : '') + `<td class="q">${r.q}</td>` +
    `<td class="num">${r.x.toFixed(2)}</td><td class="num">${r.y.toFixed(2)}</td>` +
    `<td class="num">${fmt(r.dx)}</td><td class="num">${fmt(r.dy)}</td>` +
    r.chg.map(c => `<td class="num">${fmt(c)}</td>`).join('') + '</tr>').join('');
}

function chips(){
  const c = $('#qchips'); c.textContent = '';
  const all = universe();
  for (const q of QS){
    const b = document.createElement('button');
    b.className = 'chip'; b.setAttribute('aria-pressed', state.q.has(q));
    b.innerHTML = `${q}<span class="n">${all.filter(r => r.q === q).length}</span>`;
    b.onclick = () => { state.q.has(q) ? state.q.delete(q) : state.q.add(q); rrg(); };
    c.appendChild(b);
  }
  const f = $('#ccychips'); f.textContent = '';
  f.style.display = state.mode === 'pairs' ? '' : 'none';
  for (const k of [null, ...CCY]){
    const b = document.createElement('button');
    b.className = 'chip' + (state.ccy === k ? ' sel' : '');
    b.setAttribute('aria-pressed', state.ccy === k ? 'true' : 'mixed');
    b.textContent = k || 'All pairs';
    b.onclick = () => { state.ccy = k; state.q = new Set(QS); rrg(); };
    f.appendChild(b);
  }
  const sn = $('#sidenote');
  if (state.mode === 'pairs' && state.ccy){
    sn.style.display = 'block';
    sn.innerHTML = `<strong>Hollow marks read backwards.</strong> Where ${state.ccy} is the quote leg, ` +
      `a pair in Leading means ${state.ccy} is <em>losing</em> ground to the other currency.`;
  } else sn.style.display = 'none';
  $('#sideleg').style.display = (state.mode === 'pairs' && state.ccy) ? '' : 'none';
}
function rrg(){ chips(); draw(); table(); }

function status(){
  const v = view();
  $('#status').textContent = `last completed ${v.label} candle ${v.last} · ${v.bars} bars · ${WINDOW}-bar window ≈ ${v.reach}`;
  const ps = $('#perseg'); ps.textContent = '';
  v.periods.forEach((p,i) => { const b = document.createElement('button');
    b.textContent = p.key; b.setAttribute('aria-selected', i === state.per);
    b.onclick = () => { state.per = i; status(); heat(); }; ps.appendChild(b); });
}
function all(){ status(); heat(); rrg(); }

function seg(id, items, get, set){
  const s = $(id); s.textContent = '';
  items.forEach(([val,label]) => { const b = document.createElement('button');
    b.textContent = label; b.setAttribute('aria-selected', get() === val);
    b.onclick = () => { set(val); [...s.children].forEach(c => c.setAttribute('aria-selected', c === b)); };
    s.appendChild(b); });
}
seg('#tfseg', VIEWS.map((v,i) => [i, v.label]), () => state.tf, v => { state.tf = v; state.per = 0; state.q = new Set(QS); all(); });
seg('#modeseg', [['ccy','Currencies'],['pairs','Pairs']], () => state.mode, v => { state.mode = v; state.ccy = null; state.q = new Set(QS); rrg(); });
$('#lbl').onclick = e => { state.labels = !state.labels; e.target.setAttribute('aria-pressed', state.labels); draw(); };
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', heat);
all();
"""


def render(meta, views):
    payload = {"meta": meta, "views": views}
    head = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Forex Rotation</title>
<style>{CSS}</style>
</head>
<body>
<p class="eyebrow">G10 currencies &middot; heat map &amp; relative rotation</p>
<h1>Forex Rotation</h1>
<p class="sub">The eight majors and all {meta['pairs']} crosses between them &mdash; how each moved,
and where each sits in its rotation &mdash; on 4H and Daily candles.</p>
<p class="meta">Completed candles only &middot; OANDA prices &middot; generated {meta['generated']} {meta['tz']}</p>

<div class="bar">
  <div class="seg" id="tfseg" role="tablist" aria-label="Timeframe"></div>
  <span class="status" id="status"></span>
</div>

<section class="card" aria-labelledby="h-heat">
  <div class="bar" style="justify-content:space-between">
    <h2 id="h-heat">Heat map</h2>
    <div class="seg" id="perseg" role="tablist" aria-label="Period"></div>
  </div>
  <p class="hint" id="heatdesc"></p>
  <div class="heatwrap">
    <div class="scroll"><table class="heat" id="heat"></table></div>
    <div>
      <p class="hint" style="margin-bottom:6px"><strong>Currency strength</strong> &mdash; each currency against the
      other seven (geometric mean), same period.</p>
      <div class="strength" id="strength"></div>
    </div>
  </div>
  <div class="legend">
    <span>Down<span class="ramp" id="ramp"></span>Up &nbsp;&middot;&nbsp; scale &plusmn;<span id="rampmax"></span></span>
  </div>
</section>

<section class="card" aria-labelledby="h-rrg">
  <div class="bar" style="justify-content:space-between">
    <h2 id="h-rrg">Relative rotation</h2>
    <div class="seg" id="modeseg" role="tablist" aria-label="Measure"></div>
  </div>
  <div class="filters" id="ccychips"></div>
  <div id="sidenote" class="sidenote" style="display:none"></div>
  <div class="filters">
    <span id="qchips" style="display:flex; gap:6px; flex-wrap:wrap"></span>
    <button class="chip" id="lbl" aria-pressed="true">Labels</button>
  </div>
  <div class="layout">
    <div class="plotwrap"><svg id="plot" viewBox="0 0 560 560" role="img" aria-label="Relative rotation graph"></svg></div>
    <div class="tablewrap"><table class="list"><thead id="thead"></thead><tbody id="tbody"></tbody></table></div>
  </div>
  <div class="legend">
    <span><i></i>Latest completed candle</span>
    <span id="sideleg" style="display:none"><i class="hollow"></i>Selected currency is the quote leg</span>
    <span><span class="tl"></span>Prior {meta['tail']} candles &mdash; tail direction shows rotation</span>
  </div>
</section>

<section class="note">
<p><strong>Why not myfxbook data.</strong> This follows the layout of myfxbook's forex heat map, but
its prices cannot come from there: every myfxbook page and data feed has answered with a bot challenge
since early September, the heat map included, and the only price feed it did offer was weekly. The
prices here are OANDA's, read from TradingView, for the same eight currencies.</p>
<p><strong>Heat map.</strong> Each cell is the row currency priced in the column currency, as a %
change over the selected period, so the grid is mirror-imaged across the diagonal. Blue is up, red
is down, gray is flat; the scale runs to the largest move on screen, and every cell prints its value.
Currency strength is each currency against the other seven at once &mdash; the geometric mean of its
seven rates &mdash; which is the right answer to &ldquo;who moved&rdquo;, where a single pair only ever
says which of two moved more.</p>
<p><strong>Rotation.</strong> <em>Currencies</em> plots those eight strength indices against the
equal-weighted basket of all eight. That basket is exactly 1 by construction &mdash; every cross adds
+log rate to one index and &minus;log rate to another &mdash; so there is no benchmark of its own to
tug the marks, and no weighting to argue about. <em>Pairs</em> plots each cross against that same unit,
which is simply its own price: Leading means above its recent norm and still climbing. Filter to one
currency to see its seven pairs; hollow marks are pairs where it is the quote leg, and they rotate
opposite to its strength. RS-Ratio is 100 + the z-score over {meta['window']} bars; RS-Momentum is
100 + the z-score of its {meta['roc']}-bar change. This is a standard z-score replication of the
proprietary JdK formulas: quadrant and direction track the original, exact values will not &mdash;
treat anything within ~0.3 of a boundary as unclassified.</p>
<p><strong>Completed candles only.</strong> The page refreshes five minutes after each 4H candle
closes, so the 4H view moves every refresh and the Daily view moves once a day, when the FX day closes
at 17:00 New York. The candle still forming is never plotted. Daily candles are labelled by the
trading day they cover, which is one day later than the date TradingView stamps on them.</p>
<p><strong>Not advice.</strong> A screening view of relative strength, not a recommendation to trade.</p>
</section>

<div class="tip" id="tip" role="tooltip"></div>
<script>
const DATA = {json.dumps(payload, ensure_ascii=False)};
const VIEWS = DATA.views, CCY = DATA.meta.ccy, WINDOW = DATA.meta.window;
{JS}
</script>
</body>
</html>
"""
    return head
