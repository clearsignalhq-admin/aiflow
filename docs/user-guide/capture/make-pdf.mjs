// Makes a PDF of the user guide by printing the in-app guide page (/guide) with a browser, so the PDF always matches
// what the app shows. No backend is needed: the guide is public.
//
//   node make-pdf.mjs            -> docs/user-guide/AiFlow User Guide.pdf
//
// Needs the frontend's node_modules and Playwright's Chromium (see README.md in this folder).
import { createRequire } from 'node:module';
import { spawn } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = join(HERE, '..', '..', '..');
const OUT = join(HERE, '..', 'AiFlow User Guide.pdf');
const PORT = 5194;
const version = readFileSync(join(REPO, 'VERSION'), 'utf-8').trim();
const require = createRequire(join(REPO, 'frontend', 'package.json'));
const { chromium } = require('@playwright/test');

const vite = spawn('npx', ['vite', '--port', String(PORT), '--strictPort'], {
  cwd: join(REPO, 'frontend'), shell: process.platform === 'win32', stdio: 'ignore',
  env: { ...process.env, VITE_API_BASE_URL: 'http://127.0.0.1:1', VITE_SUPABASE_URL: 'http://127.0.0.1:9', VITE_SUPABASE_ANON_KEY: 'docs', VITE_TURNSTILE_SITE_KEY: '' },
});
const stop = () => { if (process.platform === 'win32') spawn('taskkill', ['/pid', String(vite.pid), '/T', '/F'], { stdio: 'ignore' }); else vite.kill('SIGTERM'); };
process.on('exit', stop);

try {
  const until = Date.now() + 40000;
  for (;;) {
    try { if ((await fetch(`http://localhost:${PORT}/`)).ok) break; } catch { /* not up yet */ }
    if (Date.now() > until) throw new Error('the frontend did not start');
    await new Promise((r) => setTimeout(r, 400));
  }
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1000, height: 1200 }, colorScheme: 'light' });
  await context.addInitScript(() => localStorage.setItem('aiflow-theme', 'light'));      // black text on white paper
  const page = await context.newPage();
  await page.goto(`http://localhost:${PORT}/guide`);
  await page.waitForSelector('[data-testid="guide-content"] img');
  await page.$$eval('img', (imgs) => imgs.forEach((i) => { i.loading = 'eager'; }));         // lazy images would print blank
  await page.waitForFunction(() => [...document.images].every((i) => i.complete && i.naturalWidth > 0), null, { timeout: 30000 });
  await page.emulateMedia({ media: 'print' });
  const small = 'style="font-size:8px;color:#666;width:100%;padding:0 14mm;"';
  await page.pdf({
    path: OUT, format: 'A4', printBackground: true,
    margin: { top: '16mm', bottom: '16mm', left: '14mm', right: '14mm' },
    displayHeaderFooter: true,
    headerTemplate: `<div ${small}>AiFlow User Guide <span style="float:right">version ${version}</span></div>`,
    footerTemplate: `<div ${small}><span style="float:right"><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>`,
  });
  await browser.close();
  console.log(`wrote ${OUT}`);
} finally {
  stop();
}
