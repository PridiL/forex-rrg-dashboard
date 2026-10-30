/**
 * Cloud fetcher: the same closes as fetch_bars.mjs, but straight from TradingView's
 * public chart websocket instead of a live TradingView Desktop over CDP, so it runs
 * on a GitHub runner with nothing installed.
 *
 *   node fetch_bars_ws.mjs <out.json> <1D:400,240:400> <SYM> [SYM...]
 *
 * Writes {resolution: {symbol: [[epochSeconds, close], ...]}} -- byte-for-byte the
 * shape fetch_bars.mjs writes, so build.py cannot tell them apart.
 *
 * Protocol (unofficial, what the web chart itself speaks): frames are
 * "~m~<len>~m~<json>"; "~h~N" heartbeats must be echoed or the server drops us.
 * Guest token "unauthorized_user_token" is enough for OANDA FX (no delay, no login).
 * One chart session per symbol/resolution, a few in flight at once.
 *  - The server sends the series in one or more timescale_update frames and then
 *    series_completed; anything before series_completed may be partial.
 *  - Failures are retried once at the end, then reported on STDOUT and skipped;
 *    build.py treats a missing pair as fatal.
 */
import { writeFileSync } from 'fs';

const [OUT, RES_CSV, ...SYMBOLS] = process.argv.slice(2);
if (!OUT || !RES_CSV || !SYMBOLS.length) {
  console.error('usage: node fetch_bars_ws.mjs <out.json> <res[:count][,...]> <SYMBOL> [SYMBOL...]');
  process.exit(1);
}
const RESOLUTIONS = RES_CSV.split(',').map(s => s.trim()).filter(Boolean).map(part => {
  const [res, want] = part.split(':');
  return { res, want: Math.max(1, parseInt(want || '400', 10)) };
});
const URL = 'wss://data.tradingview.com/socket.io/websocket?from=chart%2F&type=chart';
const MIN_BARS = 90;
const PARALLEL = 4;
const TIMEOUT_MS = 30000;

const frame = obj => { const s = JSON.stringify(obj); return `~m~${s.length}~m~${s}`; };
function unframe(data) {
  const out = [];
  let i = 0;
  while (i < data.length) {
    const m = /^~m~(\d+)~m~/.exec(data.slice(i));
    if (!m) break;
    const start = i + m[0].length, len = +m[1];
    out.push(data.slice(start, start + len));
    i = start + len;
  }
  return out;
}
const rand = () => Math.random().toString(36).slice(2, 14);

function fetchSeries(sym, res, want) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(URL, { headers: { Origin: 'https://www.tradingview.com' } });
    const cs = 'cs_' + rand();
    const bars = new Map();
    const timer = setTimeout(() => { ws.close(); reject(new Error('timeout')); }, TIMEOUT_MS);
    const done = (err, val) => { clearTimeout(timer); try { ws.close(); } catch {} err ? reject(err) : resolve(val); };
    const send = (m, p) => ws.send(frame({ m, p }));
    ws.onerror = e => done(new Error('socket error ' + (e.message || '')));
    ws.onmessage = ev => {
      for (const msg of unframe(String(ev.data))) {
        if (msg.startsWith('~h~')) { ws.send(`~m~${msg.length}~m~${msg}`); continue; }
        let j; try { j = JSON.parse(msg); } catch { continue; }
        if (j.session_id) {   // server hello: start the session
          send('set_auth_token', ['unauthorized_user_token']);
          send('chart_create_session', [cs, '']);
          send('resolve_symbol', [cs, 'sym1', '=' + JSON.stringify({ symbol: sym, adjustment: 'splits' })]);
          send('create_series', [cs, 's1', 's1', 'sym1', res, want, '']);
          continue;
        }
        if (j.m === 'symbol_error') return done(new Error('symbol_error ' + JSON.stringify(j.p).slice(0, 120)));
        if (j.m === 'series_error') return done(new Error('series_error ' + JSON.stringify(j.p).slice(0, 120)));
        if (j.m === 'protocol_error' || j.m === 'critical_error') return done(new Error(j.m + ' ' + JSON.stringify(j.p).slice(0, 120)));
        if (j.m === 'timescale_update' || j.m === 'du') {
          for (const b of j.p?.[1]?.s1?.s || []) bars.set(b.v[0], b.v[4]);
        }
        if (j.m === 'series_completed') {
          const out = [...bars.entries()].sort((a, b) => a[0] - b[0]).slice(-want);
          return done(null, out);
        }
      }
    };
  });
}

const out = {};
for (const { res } of RESOLUTIONS) out[res] = {};
const jobs = SYMBOLS.flatMap(sym => RESOLUTIONS.map(r => [sym, r]));

async function runOne([sym, r]) {
  try {
    const bars = await fetchSeries(sym, r.res, r.want);
    if (bars.length < MIN_BARS) return `only ${bars.length} bars`;
    out[r.res][sym] = bars;
    return null;
  } catch (e) { return String(e.message || e).slice(0, 120); }
}

async function pool(list, label) {
  const failed = [];
  let k = 0;
  await Promise.all(Array.from({ length: PARALLEL }, async () => {
    while (k < list.length) {
      const job = list[k++];
      const why = await runOne(job);
      const [sym, r] = job;
      console.log(`${label}${sym} @ ${r.res}: ${why ? 'FAILED ' + why : out[r.res][sym].length}`);
      if (why) failed.push(job);
    }
  }));
  return failed;
}

const retry = await pool(jobs, '');
const failed = retry.length ? await pool(retry, 'retry ') : [];

writeFileSync(OUT, JSON.stringify(out));
console.log(`wrote ${OUT}: ` + RESOLUTIONS.map(({ res }) => `${res}=${Object.keys(out[res]).length}/${SYMBOLS.length}`).join(' ')
  + (failed.length ? `  failed: ${failed.map(([s, r]) => `${s}@${r.res}`).join(', ')}` : ''));
