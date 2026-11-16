// Drive one OIUI chat: new browser context, send prompt(s), time AG-UI events, log outside requests, screenshot.
// usage: node run-prompt.js <outdir> <jobs.json>   jobs.json: [{nn, text}] (several entries = same chat, follow-ups)
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const [outdir, jobsFile] = process.argv.slice(2);
const jobs = JSON.parse(fs.readFileSync(jobsFile, 'utf8'));
const USAGE = process.env.USAGE_LOG;
const SHOTS = process.env.SHOTS;
const PRICE = { in: 2 / 1e6, out: 10 / 1e6, cw5: 2.5 / 1e6, cw1h: 4 / 1e6, cr: 0.1 / 1e6 };

function costOf(u) {
  const cc = u.cache_creation || {};
  const cw1h = cc.ephemeral_1h_input_tokens || 0;
  const cw5 = (u.cache_creation_input_tokens || 0) - cw1h;
  return (u.input_tokens || 0) * PRICE.in + (u.output_tokens || 0) * PRICE.out +
    cw5 * PRICE.cw5 + cw1h * PRICE.cw1h + (u.cache_read_input_tokens || 0) * PRICE.cr;
}
function usageSince(t0) {
  if (!fs.existsSync(USAGE)) return [];
  return fs.readFileSync(USAGE, 'utf8').trim().split('\n').filter(Boolean).map(JSON.parse)
    .filter(r => r.kind === 'anthropic' && r.t0 >= t0);
}

const INIT = `
(() => {
  if (window.top !== window) return;
  window.__agui = [];
  const of = window.fetch;
  window.fetch = async function (input, init) {
    const url = typeof input === 'string' ? input : (input && input.url) || '';
    const res = await of.apply(this, arguments);
    if (url.includes('/api/copilotkit') && res.body) {
      const [a, b] = res.body.tee();
      const rd = b.getReader(); const dec = new TextDecoder(); let buf = '';
      const reqT = Date.now();
      window.__agui.push({ t: reqT, type: '__REQUEST' });
      (async () => {
        for (;;) {
          const { value, done } = await rd.read(); if (done) break;
          buf += dec.decode(value, { stream: true });
          let i;
          while ((i = buf.indexOf('\\n')) >= 0) {
            const line = buf.slice(0, i).trim(); buf = buf.slice(i + 1);
            if (!line.startsWith('data:')) continue;
            try {
              const ev = JSON.parse(line.slice(5));
              const rec = { t: Date.now(), type: ev.type };
              if (ev.toolCallName) rec.tool = ev.toolCallName;
              if (ev.type === 'RUN_ERROR') rec.msg = String(ev.message || '').slice(0, 300);
              if (ev.type === 'TEXT_MESSAGE_CONTENT') rec.len = (ev.delta || '').length;
              if (ev.type === 'TOOL_CALL_ARGS') { rec.len = (ev.delta || '').length; window.__argn = (window.__argn || 0) + 1; if (window.__argn <= 4) rec.head = String(ev.delta || '').slice(0, 60); }
              if (ev.type === 'TOOL_CALL_START') window.__argn = 0;
              window.__agui.push(rec);
            } catch (e) {}
          }
        }
        window.__agui.push({ t: Date.now(), type: '__STREAM_END' });
      })();
      return new Response(a, { status: res.status, statusText: res.statusText, headers: res.headers });
    }
    return res;
  };
})();`;

(async () => {
  fs.mkdirSync(outdir, { recursive: true });
  const browser = await chromium.launch({ args: ['--disable-dev-shm-usage', '--disable-gpu'] });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await ctx.addInitScript(INIT);
  const reqs = [];
  const T = () => Date.now();
  ctx.on('request', r => reqs.push({ t: T(), ev: 'req', url: r.url(), method: r.method(), rtype: r.resourceType() }));
  ctx.on('requestfailed', r => reqs.push({ t: T(), ev: 'failed', url: r.url(), err: (r.failure() || {}).errorText }));
  ctx.on('response', r => { if (!/127\.0\.0\.1|^data:|^blob:/.test(r.url())) reqs.push({ t: T(), ev: 'resp', url: r.url(), status: r.status() }); });
  const page = await ctx.newPage();
  const consoleErr = [];
  page.on('console', m => { if (m.type() === 'error') consoleErr.push(m.text().slice(0, 300)); });
  page.on('pageerror', e => consoleErr.push('pageerror: ' + String(e).slice(0, 300)));
  await page.goto('http://127.0.0.1:3000/', { waitUntil: 'domcontentloaded', timeout: 300000 });
  const input = page.locator('textarea').first();
  await input.waitFor({ timeout: 300000 });
  await page.waitForTimeout(3000);
  const results = [];
  for (const job of jobs) {
    const startIdx = await page.evaluate(() => window.__agui.length);
    // The shipped chat view gates every send on BYOK OpenAI+Jev keys (key-gated-chat-view.tsx). Call CopilotChat's own
    // ungated submit handler (the outermost onSubmitMessage above the textarea) so the run uses the server's keys.
    const t0 = Date.now();
    const how = await page.evaluate((text) => {
      const ta = document.querySelector('textarea');
      const key = Object.keys(ta).find(k => k.startsWith('__reactFiber$'));
      let f = ta[key], outer = null, n = 0;
      while (f) { const pr = f.memoizedProps; if (pr && typeof pr.onSubmitMessage === 'function') { outer = pr; n++; } f = f.return; }
      if (!outer) return 'no-handler';
      outer.onSubmitMessage(text);
      return 'submitted via outermost of ' + n;
    }, job.text);
    console.error('submit:', how);
    let lastActivity = t0, firstEvt = null, runFinished = null, aborted = null, cost = 0;
    for (;;) {
      await page.waitForTimeout(1000);
      const evs = (await page.evaluate(() => window.__agui)).slice(startIdx);
      const meaningful = evs.filter(e => /^(TEXT_MESSAGE_CONTENT|TOOL_CALL_START|TOOL_CALL_ARGS)$/.test(e.type));
      if (!firstEvt && meaningful.length) firstEvt = meaningful[0];
      if (evs.length) lastActivity = Math.max(lastActivity, evs[evs.length - 1].t);
      const reqsOpen = evs.filter(e => e.type === '__REQUEST').length - evs.filter(e => e.type === '__STREAM_END').length;
      const fin = evs.filter(e => e.type === 'RUN_FINISHED' || e.type === 'RUN_ERROR');
      cost = usageSince(t0 / 1000 - 1).reduce((s, r) => s + costOf(r.usage || {}), 0);
      if (cost > 2.0) { aborted = 'cost>2'; break; }
      if (fin.length && reqsOpen <= 0 && Date.now() - lastActivity > 12000) { runFinished = fin[fin.length - 1]; break; }
      if (Date.now() - t0 > 900000) { aborted = 'timeout900s'; break; }
    }
    const evs = (await page.evaluate(() => window.__agui)).slice(startIdx);
    // let sandboxes load CDN libs / tiles / images
    await page.waitForTimeout(15000);
    const name = job.nn;
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.waitForTimeout(1500);
    await page.screenshot({ path: path.join(SHOTS, `${name}-1440.png`) });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(2500);
    await page.screenshot({ path: path.join(SHOTS, `${name}-390.png`) });
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.waitForTimeout(1500);
    const tools = evs.filter(e => e.type === 'TOOL_CALL_START').map(e => e.tool);
    const errors = evs.filter(e => e.type === 'RUN_ERROR');
    const endT = (runFinished && runFinished.t) || Date.now();
    const usage = usageSince(t0 / 1000 - 1).filter(r => r.t0 <= endT / 1000 + 1);
    const sum = k => usage.reduce((s, r) => s + ((r.usage || {})[k] || 0), 0);
    results.push({
      nn: name, text: job.text, t0, ttft_s: firstEvt ? (firstEvt.t - t0) / 1000 : null,
      first_type: firstEvt && firstEvt.type, total_s: (endT - t0) / 1000, aborted,
      argHeads: evs.filter(e => e.head !== undefined).map(e => e.head), evTypes: evs.reduce((m, e) => (m[e.type] = (m[e.type] || 0) + 1, m), {}),
      tools, errors, runs: evs.filter(e => e.type === 'RUN_STARTED').length,
      text_chars: evs.filter(e => e.type === 'TEXT_MESSAGE_CONTENT').reduce((s, e) => s + (e.len || 0), 0),
      anthropic_calls: usage.length, input_tokens: sum('input_tokens'), output_tokens: sum('output_tokens'),
      cache_write: sum('cache_creation_input_tokens'), cache_read: sum('cache_read_input_tokens'),
      cost_usd: usage.reduce((s, r) => s + costOf(r.usage || {}), 0), anth_status: usage.map(r => r.status),
    });
    if (aborted === 'cost>2') break;
  }
  const lastText = await page.evaluate(() => document.body.innerText.slice(-4000));
  const frames = page.frames().map(f => f.url().slice(0, 120));
  fs.writeFileSync(path.join(outdir, 'result.json'), JSON.stringify({ results, consoleErr: consoleErr.slice(0, 40), frames, lastText }, null, 1));
  fs.writeFileSync(path.join(outdir, 'requests.json'), JSON.stringify(reqs, null, 0));
  await browser.close();
  console.log(JSON.stringify(results.map(r => ({ nn: r.nn, ttft: r.ttft_s, total: r.total_s, tools: r.tools, cost: r.cost_usd.toFixed(4), aborted: r.aborted, errors: r.errors.length }))));
})().catch(e => { console.error('DRIVER ERROR', e); process.exit(1); });
