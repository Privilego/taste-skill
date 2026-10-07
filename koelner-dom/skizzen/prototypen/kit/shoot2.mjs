import { chromium } from '/opt/node22/lib/node_modules/playwright/index.mjs';
import fs from 'fs'; import path from 'path';
// usage: node shoot2.mjs <modelDir> <outDir> '<views json>' '<init json>'
const [modelDir, outDir, viewsJson, initJson] = process.argv.slice(2);
const root = path.dirname(new URL(import.meta.url).pathname);
const views = JSON.parse(viewsJson); const init = JSON.parse(initJson || '{}');
fs.mkdirSync(outDir, { recursive: true });
const browser = await chromium.launch({ args: ['--use-angle=swiftshader','--enable-unsafe-swiftshader','--ignore-gpu-blocklist'] });
const page = await browser.newPage({ viewport: { width: 1100, height: 1100 } });
page.on('pageerror', e => console.log('pageerror', e.message));
await page.route('**/*', async (route) => {
  const u = new URL(route.request().url()); const p = decodeURIComponent(u.pathname);
  const f = p === '/' ? path.join(root, 'render2.html') : p.startsWith('/node_modules') ? path.join(root, p) : path.join(modelDir, p);
  if (!fs.existsSync(f)) return route.fulfill({ status: 404, body: '' });
  const ct = f.endsWith('.js') ? 'text/javascript' : f.endsWith('.html') ? 'text/html' : f.endsWith('.json') ? 'application/json' : 'application/octet-stream';
  route.fulfill({ status: 200, body: fs.readFileSync(f), headers: { 'content-type': ct } });
});
await page.addInitScript(`Object.assign(window, ${JSON.stringify(init)});`);
await page.goto('http://local/');
await page.waitForFunction(() => window.ready === true, null, { timeout: 180000 });
for (const v of views) { await page.evaluate((v) => window.shot(v), v); await page.screenshot({ path: path.join(outDir, v.name + '.png') }); console.log(path.join(outDir, v.name + '.png')); }
await browser.close();
