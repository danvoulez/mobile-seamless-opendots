// The iPhone when things go wrong: locked mid-reply, the Mac going away, a
// message written while it's away, and reconnecting by itself.
// Starts and stops its own API server (run.sh stops the shared one first).
import { spawn } from 'node:child_process';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { devices } from 'playwright';
import { API, ROOT, TOKEN, launch, ok, owner, suite, useFakeModel } from './lib.mjs';

const { log, shot, check, watch } = suite('resilience');
const python = process.env.E2E_PYTHON || join(ROOT, 'server/.venv/bin/python');
const env = { ...process.env, DATA_DIR: mkdtempSync(join(tmpdir(), 'open-dots-resilience-')), APP_AUTH_TOKEN: TOKEN };
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

let server;
async function startServer() {
  server = spawn(python, ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000'], {
    cwd: join(ROOT, 'server'), env, stdio: 'ignore',
  });
  for (let i = 0; i < 80; i++) {
    try {
      if ((await fetch(`${API}/api/v1/health`)).ok) return;
    } catch { /* not up yet */ }
    await sleep(250);
  }
  throw new Error('the API did not start');
}

try {
  await startServer();
  const mac = await owner();
  await useFakeModel(mac);
  const { code } = await ok(await mac.post('/api/v1/devices/pairing'));

  const browser = await launch();
  const context = await browser.newContext({ ...devices['iPhone 15'], baseURL: API });
  let phone = await context.newPage();
  await phone.goto('/m/');
  await phone.locator('#pair-code').fill(code);
  await phone.getByRole('button', { name: 'Link', exact: true }).click();
  await phone.locator('.status-live').waitFor();

  // 1. Send, then "lock" the phone right away: the reply keeps going on the Mac.
  await phone.getByRole('button', { name: 'New chat' }).click();
  check('the list is inert under the sheet', await phone.evaluate(() => document.querySelector('.screen-list').inert));
  await phone.locator('.sheet').getByRole('button', { name: /Open Dots Assistant/ }).click();
  check('the list is interactive again', await phone.evaluate(() => !document.querySelector('.screen-list').inert));
  await phone.locator('.pill textarea').fill('Keep going while my phone is locked');
  await phone.locator('.send-btn').click();
  await phone.locator('.bubble-bot.streaming').waitFor();
  await phone.close();
  await sleep(7000);
  const threads = await ok(await mac.get('/api/v1/threads'));
  const detail = await ok(await mac.get(`/api/v1/threads/${threads[0].id}`));
  const last = detail.messages.at(-1);
  check('the reply finished without the phone', detail.thread.status === 'idle' && last.sender === 'bot' && !last.is_error);
  phone = await context.newPage();
  watch(phone, 'phone');
  await phone.goto('/m/');
  await phone.locator('.continue-card').click();
  await phone.getByText('Anything else?').waitFor();
  check('the reopened phone shows the finished reply', true);

  // 2. The Mac goes away: the phone keeps its chats and says so.
  await phone.locator('.back-btn').click();
  const caches = await phone.evaluate(async () => { await navigator.serviceWorker.ready; return (await caches.keys()).join(','); });
  check('the app keeps a copy of itself', caches.includes('open-dots'));
  server.kill('SIGTERM');
  await sleep(1500);
  await phone.reload();
  await phone.locator('.status-reconnecting').waitFor({ timeout: 15000 });
  check('chats are still there while the Mac is away', (await phone.locator('.continue-card, .row').count()) >= 1);
  await phone.screenshot({ path: shot('01-mac-away') });

  // 3. A message written while it's away waits, even across a reload.
  await phone.getByRole('button', { name: 'New chat' }).click();
  await phone.locator('.sheet').getByRole('button', { name: /Claude Architect/ }).click();
  await phone.locator('.pill textarea').fill('Written while the Mac was away');
  await phone.locator('.send-btn').click();
  await phone.getByText('Waiting for').waitFor();
  await phone.screenshot({ path: shot('02-waiting-to-send') });
  await phone.reload();
  await phone.getByText('Waiting to send').waitFor();
  await phone.screenshot({ path: shot('03-list-waiting') });
  check('the waiting message survived a reload', true);

  // 4. The Mac comes back: the phone reconnects and sends by itself.
  await startServer();
  await phone.locator('.status-live').waitFor({ timeout: 30000 });
  check('the phone reconnected by itself', true);
  await phone.getByText('Waiting to send').waitFor({ state: 'detached', timeout: 15000 });
  const after = await ok(await mac.get('/api/v1/threads'));
  const sent = after.find((thread) => thread.title === 'Written while the Mac was away');
  check('the waiting chat reached the Mac', Boolean(sent));
  let replied = false;
  for (let i = 0; i < 40 && !replied; i++) {
    const current = await ok(await mac.get(`/api/v1/threads/${sent.id}`));
    replied = current.thread.status === 'idle' && current.messages.at(-1)?.sender === 'bot';
    if (!replied) await sleep(500);
  }
  check('and got a reply', replied);
  await phone.screenshot({ path: shot('04-reconnected') });
  log('done');
  await browser.close();
  await mac.dispose();
} finally {
  server?.kill();
}
