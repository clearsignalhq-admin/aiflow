// Regenerates every screenshot in docs/user-guide/images from a clean state:
//   node run.mjs [only-this-shot-prefix]
// Starts the local backend (port 8765) and the frontend (port 5199) with fake credentials, runs capture.mjs, stops both.
// Needs: the backend virtual environment (backend/.venv) and the frontend's node_modules.
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = join(HERE, '..', '..', '..');
const python = [join(REPO, 'backend', '.venv', 'Scripts', 'python.exe'), join(REPO, 'backend', '.venv', 'bin', 'python')].find(existsSync) ?? 'python';
const API_PORT = 8765, APP_PORT = 5199;
const children = [];

function start(cmd, args, options) {
  const child = spawn(cmd, args, { stdio: 'ignore', shell: process.platform === 'win32' && cmd === 'npx', ...options });
  children.push(child);
  return child;
}
async function waitFor(url, label, ms = 40000) {
  const until = Date.now() + ms;
  while (Date.now() < until) {
    try { if ((await fetch(url)).ok) return; } catch { /* not up yet */ }
    await new Promise((r) => setTimeout(r, 400));
  }
  throw new Error(`${label} did not start within ${ms / 1000}s`);
}
function stopAll() {
  for (const c of children) {
    try {
      if (process.platform === 'win32') spawn('taskkill', ['/pid', String(c.pid), '/T', '/F'], { stdio: 'ignore' });
      else c.kill('SIGTERM');
    } catch { /* already gone */ }
  }
}
process.on('exit', stopAll);
process.on('SIGINT', () => { stopAll(); process.exit(130); });

try {
  start(python, ['server.py'], { cwd: HERE, env: { ...process.env, PORT: String(API_PORT) } });
  start('npx', ['vite', '--port', String(APP_PORT), '--strictPort'], {
    cwd: join(REPO, 'frontend'),
    env: { ...process.env, VITE_API_BASE_URL: `http://127.0.0.1:${API_PORT}`, VITE_SUPABASE_URL: 'http://127.0.0.1:9', VITE_SUPABASE_ANON_KEY: 'docs', VITE_TURNSTILE_SITE_KEY: '' },
  });
  await waitFor(`http://127.0.0.1:${API_PORT}/api/health`, 'the local backend');
  await waitFor(`http://localhost:${APP_PORT}/`, 'the frontend');
  const capture = start('node', ['capture.mjs', ...process.argv.slice(2)], { cwd: HERE, stdio: 'inherit' });
  const code = await new Promise((resolve) => capture.on('exit', resolve));
  process.exitCode = code ?? 1;
} catch (err) {
  console.error(String(err));
  process.exitCode = 1;
} finally {
  stopAll();
}
