// Takes the screenshots used by the user guide, by driving the real interface with Playwright.
//
//   1. python server.py                       (this folder: the local backend, port 8765, no real services)
//   2. cd ../../../frontend && VITE_API_BASE_URL=http://127.0.0.1:8765 VITE_SUPABASE_URL=http://127.0.0.1:9 \
//        VITE_SUPABASE_ANON_KEY=docs VITE_TURNSTILE_SITE_KEY= npx vite --port 5199 --strictPort
//   3. node capture.mjs [only-this-shot-prefix]
//
// Or just run:  node run.mjs   (starts both servers, captures, stops them)
import { createRequire } from 'node:module';
import { mkdirSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = join(HERE, '..', '..', '..');
const require = createRequire(join(REPO, 'frontend', 'package.json'));
const { chromium } = require('@playwright/test');

const APP = process.env.CAPTURE_APP ?? 'http://localhost:5199';
const API = process.env.CAPTURE_API ?? 'http://127.0.0.1:8765';
const OUT = join(HERE, '..', 'images');
const only = process.argv[2];
mkdirSync(OUT, { recursive: true });

const example = (path) => JSON.parse(readFileSync(join(REPO, 'examples', path), 'utf-8'));

// A signed-in browser without any real account: a session that does not expire, under the key supabase-js reads.
const session = {
  access_token: 'docs', refresh_token: 'docs', token_type: 'bearer', expires_in: 315360000,
  expires_at: Math.floor(Date.now() / 1000) + 315360000,
  user: { id: 'docs-user', aud: 'authenticated', role: 'authenticated', email: 'ada@example.com', app_metadata: {}, user_metadata: { name: 'Ada Lovelace' }, created_at: '2026-01-01T00:00:00Z' },
};

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1440, height: 860 }, deviceScaleFactor: 1, colorScheme: 'dark' });
await context.addInitScript((s) => {
  localStorage.setItem('sb-127-auth-token', JSON.stringify(s));
  localStorage.setItem('aiflow-theme', 'dark');
}, session);
const page = await context.newPage();
page.on('pageerror', (e) => console.log('  page error:', e.message));
page.on('dialog', (d) => d.accept());                 // "discard unsaved changes?" and similar: say yes

let taken = 0;
async function shot(name, locator) {
  if (only && !name.startsWith(only)) return;
  await page.waitForTimeout(350);                       // let animations settle
  await (locator ?? page).screenshot({ path: join(OUT, `${name}.png`) });
  taken++;
  console.log('  captured', name);
}
const run = (name, fn) => async () => {
  if (only && !name.startsWith(only) && !only.startsWith('all')) { /* steps still run so state builds up */ }
  await fn();
};

async function menu(name, item) {
  await page.getByRole('button', { name, exact: false }).filter({ hasText: name }).first().click();
  if (item) await page.getByRole('menuitem', { name: item }).click();
}
const closeDialog = async () => { await page.keyboard.press('Escape'); await page.waitForTimeout(150); };
const dialog = (name) => page.getByRole('dialog', { name });
const api = async (method, path, body) => {
  const res = await fetch(`${API}${path}`, { method, headers: { 'Content-Type': 'application/json', Authorization: 'Bearer docs' }, body: body ? JSON.stringify(body) : undefined });
  if (!res.ok) throw new Error(`${method} ${path} -> ${res.status} ${await res.text()}`);
  return res.status === 204 ? null : res.json();
};

// ── Steps ────────────────────────────────────────────────────────────────────
const supply = example('complex/supply-chain-monitor.json');

await page.goto(`${APP}/app`);
await page.waitForSelector('.toolbar');

// 1. The empty editor, the menus, the examples
await shot('01-editor-empty');
await menu('File');
await shot('02-file-menu');
await page.getByRole('menuitem', { name: 'Examples…' }).click();
await page.waitForSelector('.modal');
await shot('03-examples');

// 2. Load an example; a step's settings; the design check
await page.getByText(supply.name).first().click();
await page.waitForSelector('.react-flow__node:has-text("Poll Inventory")', { timeout: 8000 });
await page.waitForTimeout(900);
await page.waitForTimeout(3500);                                   // let the "Loaded: ..." notice fade
await shot('04-editor-example');
await page.locator('.react-flow__node').filter({ hasText: 'Poll Inventory' }).first().click();
await shot('05-properties');
await page.mouse.click(1000, 560);
await page.getByRole('button', { name: /^Validate/ }).click();
await page.waitForSelector('.validation-panel');
await page.waitForTimeout(500);
await shot('06-validate');

// 3. Safety checks, before anything is fixed
await menu('Analyze', 'Safety checks');
await page.waitForSelector('[data-testid="exposure"]');
await page.getByRole('button', { name: 'Run failure drill' }).click();
await page.waitForSelector('[data-testid="drill"]');
await shot('07-safety', dialog('Safety checks'));
await closeDialog();

// 4. Simulate
await page.getByRole('button', { name: /Simulate/ }).first().click();
await page.waitForSelector('.modal');
await shot('08-simulate-setup', page.locator('.modal').first());
await page.getByRole('button', { name: 'Run Simulation' }).click();
await page.waitForTimeout(10000);
await shot('09-simulate-result');

// 5. A test suite: made through the API, run through the interface
const stored = await page.evaluate(() => JSON.parse(localStorage.getItem('aiflow:workflow')));
const suite = await api('POST', '/api/suites', {
  name: 'Shortage routing', workflow_id: stored.id,
  cases: [
    { name: 'A critical shortage raises an alert', input: { warehouse_id: 'WH-EAST-01' }, seed: 0,
      assertions: [{ type: 'visits_node', node_id: 'send-alert' }, { type: 'skips_node', node_id: 'llm-recommend' }, { type: 'max_steps', max_steps: 12 }] },
    { name: 'A small shortage is only logged', input: { warehouse_id: 'WH-WEST-02' }, seed: 2,
      assertions: [{ type: 'visits_node', node_id: 'llm-recommend' }, { type: 'skips_node', node_id: 'send-alert' }] },
    { name: 'Every run records something', input: { warehouse_id: 'WH-EAST-01' }, seed: 3,
      assertions: [{ type: 'visits_node', node_id: 'log-recommendation' }] },
  ],
});
await page.getByRole('button', { name: 'Tests', exact: true }).click();
await page.waitForSelector('[aria-label="Test suites"]');
await page.waitForTimeout(700);
await shot('10-tests-cases', dialog('Test suites'));
await page.getByRole('button', { name: /▶ Run 3 cases/ }).click();
await page.waitForSelector('[data-testid="pass-rate"]', { timeout: 30000 });
await page.locator('[data-testid="pass-rate"]').evaluate((el) => el.scrollIntoView({ block: 'start' }));
await page.waitForTimeout(500);
await shot('11-tests-report', dialog('Test suites'));
await closeDialog();

// 6. The same suite on a "refactored" workflow: the alert branch is never taken any more
const refactored = JSON.parse(JSON.stringify(stored));
refactored.nodes.find((n) => n.id === 'critical-check').config.expression = '"non-critical"';
const run2 = await api('POST', `/api/suites/${suite.id}/runs`, { workflow: refactored, seed: 0 });
for (const c of run2.cases) await api('POST', `/api/suite-runs/${run2.id}/cases/${c.id}/run`);
await page.getByRole('button', { name: 'Tests', exact: true }).click();
await page.waitForSelector('[aria-label="Test suites"]');
await page.waitForTimeout(600);
await page.locator('.suite-history-list button').first().click();
await page.waitForSelector('#compare-base');
await page.getByRole('button', { name: 'Compare', exact: true }).click();
await page.waitForSelector('[data-testid="cmp-verdict"]');
await page.locator('.cmp').evaluate((el) => el.scrollIntoView({ block: 'start' }));
await page.waitForTimeout(500);
await shot('12-compare-runs', dialog('Test suites'));
await closeDialog();

// 7. Cloud: save, apply the suggested fixes, save again, look at the history, share
await menu('File', 'Cloud workflows…');
await page.waitForSelector('[aria-label="Cloud workflows"]');
await page.getByLabel('Version note').fill('First version, as loaded');
await page.getByRole('button', { name: 'Save as new cloud workflow' }).click();
await page.waitForSelector('[data-testid="cloud-item"]');
await shot('13-cloud-save', dialog('Cloud workflows'));
await closeDialog();

await menu('Analyze', 'Suggest changes');
await page.waitForSelector('[data-testid="change-card"]');
await page.waitForTimeout(500);
await shot('14-suggest', dialog('Suggested changes'));
await page.getByRole('button', { name: /Apply all \d+ fixes/ }).click();
await page.waitForSelector('[role="status"]');
await shot('15-suggest-applied', dialog('Suggested changes'));
await closeDialog();
await page.waitForTimeout(3800);                                   // fade the notice, let the view refit
await shot('16-editor-after-fixes');

await menu('File', 'Cloud workflows…');
await page.waitForSelector('[data-testid="cloud-item"]');
await page.getByLabel('Version note').fill('Added failure branches');
await page.getByRole('button', { name: /^Save to / }).click();
await page.waitForSelector('text=Saved as version 2');
await page.getByRole('button', { name: /^Versions of / }).click();
await page.waitForSelector('[data-testid="versions"]');
await page.getByRole('button', { name: 'Changes since version 1' }).click();
await page.waitForSelector('[data-testid="version-diff"]');
await shot('17-cloud-versions', dialog('Cloud workflows'));
await page.getByRole('button', { name: /^Share / }).click();
const link = await page.getByLabel('Share link').inputValue();
await shot('18-cloud-share', dialog('Cloud workflows'));
await closeDialog();

const visitor = await browser.newContext({ viewport: { width: 1280, height: 760 }, colorScheme: 'dark' });
const vp = await visitor.newPage();
await vp.goto(link.replace(/^https?:\/\/[^/]+/, APP));
await vp.waitForSelector('[data-testid="shared-canvas"] .react-flow__node');
await vp.waitForTimeout(800);
if (!only || '19-shared-page'.startsWith(only)) { await vp.screenshot({ path: join(OUT, '19-shared-page.png') }); taken++; console.log('  captured 19-shared-page'); }
await visitor.close();

// 8. Export, explain, search, about, generate
await menu('Export', 'Code (Python, LangGraph, MCP)');
await page.waitForSelector('[aria-label="Export code"]');
await page.waitForTimeout(500);
await shot('20-export-code', dialog('Export code'));
await closeDialog();
await menu('Export', 'Mermaid diagram');
await page.waitForSelector('[aria-label="Mermaid"]');
await shot('21-mermaid', dialog('Mermaid'));
await closeDialog();
await menu('Analyze', 'Explain');
await page.waitForSelector('[aria-label="Explain workflow"] h1, [aria-label="Explain workflow"] h2');
await page.waitForTimeout(500);
await shot('22-explain', dialog('Explain workflow'));
await closeDialog();

await page.keyboard.press('Control+k');
await page.getByRole('combobox', { name: 'Search actions' }).fill('export');
await shot('23-command-palette', page.locator('.cp'));
await closeDialog();
await menu('Help', 'About AiFlow');
await page.waitForSelector('[data-testid="about-version"]');
await shot('24-about', dialog('About AiFlow'));
await closeDialog();

await page.getByRole('button', { name: 'Generate', exact: true }).click();
await page.waitForSelector('.modal');
await page.locator('.modal textarea').first().fill('When a support email arrives, classify it, look up the customer, draft a reply, and send it to a person for approval before it goes out.');
await shot('25-generate', page.locator('.modal').first());
await closeDialog();

await browser.close();
console.log(`done: ${taken} screenshot(s) in ${OUT}`);
