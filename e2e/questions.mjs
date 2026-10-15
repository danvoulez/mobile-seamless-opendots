// A question from OpenCode on the Mac and the iPhone together: an assistant
// with tools asks the person to choose, both devices show the choices, the
// phone answers with one tap, the Mac sees the answer, and the reply uses it.
// Needs OpenCode (`npm ci` in agent/): this assistant replies through it.
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { devices } from 'playwright';
import { API, TOKEN, WEB, launch, ok, owner, suite, useFakeModel } from './lib.mjs';

const { log, shot, check, watch, errors } = suite('questions');
const api = await owner();
await useFakeModel(api);
const bot = await ok(await api.post('/api/v1/bots', {
  data: {
    name: 'Builder', model: 'fake-coder', engine: 'opencode', system_prompt: 'You build things.',
    project_dir: mkdtempSync(join(tmpdir(), 'open-dots-questions-')),
  },
}));

const browser = await launch();

// ---- iPhone: linked with a QR link
const pairing = await ok(await api.post('/api/v1/devices/pairing'));
const phoneContext = await browser.newContext({ ...devices['iPhone 15'], baseURL: API });
const phone = await phoneContext.newPage();
watch(phone, 'phone');
await phone.goto(`/m/?pair=${pairing.code}`);
await phone.getByText('Use in Safari').click();
await phone.getByRole('heading', { name: 'Chats' }).waitFor();
await phone.locator('.status-live').waitFor();

// ---- Mac: signed in with the owner token
const macContext = await browser.newContext({ viewport: { width: 1360, height: 860 }, deviceScaleFactor: 2 });
const mac = await macContext.newPage();
watch(mac, 'mac');
await mac.goto(`${WEB}/`);
await mac.locator('#owner-token').fill(TOKEN);
await mac.getByRole('button', { name: 'Sign in' }).click();
await mac.getByText('Continue on iPhone').waitFor();

// ---- The assistant asks; both devices show the question
const thread = await ok(await api.post('/api/v1/threads', { data: { bot_id: bot.id } }));
await ok(await api.post(`/api/v1/threads/${thread.id}/messages`, { data: { text: 'Please ask me which database' } }));

await phone.locator('.continue-card').click();
await phone.locator('.step-question').waitFor({ timeout: 120000 });
await phone.waitForTimeout(300);
await phone.screenshot({ path: shot('01-phone-question') });
check('the phone shows the question', await phone.getByText('Which database?').isVisible());
check('with its choices', await phone.getByRole('button', { name: 'Postgres' }).isVisible());

// The Mac lists the chat by its first message.
await mac.getByText('Please ask me which', { exact: false }).first().click();
await mac.getByText('Asks you').waitFor({ timeout: 30000 });
await mac.screenshot({ path: shot('02-mac-question') });
check('the Mac shows the same question', await mac.getByRole('button', { name: 'SQLite' }).isVisible());

// ---- Answered on the phone with one tap; the Mac sees it
await phone.getByRole('button', { name: 'Postgres' }).click();
await phone.locator('.step-question').waitFor({ state: 'detached' });
await phone.getByText('Answered: Postgres').waitFor();
await mac.getByText('Answered: Postgres').waitFor();
check('the Mac sees the answer given on the phone', true);
// The reply goes on once the model has the answer.
let reply;
for (let tries = 0; tries < 120 && reply?.sender !== 'bot'; tries += 1) {
  if (tries) await phone.waitForTimeout(500);
  reply = (await ok(await api.get(`/api/v1/threads/${thread.id}`))).messages.at(-1);
}
await phone.locator('.bubble-bot', { hasText: 'Noted:' }).waitFor();
// On the Mac: in the chat list's preview and in the conversation itself.
await mac.getByText('Noted:', { exact: false }).nth(1).waitFor();
await phone.screenshot({ path: shot('03-phone-answered') });
await mac.screenshot({ path: shot('04-mac-answered') });
log('reply', reply.text.slice(0, 120));
check('the reply uses the answer', reply.text.includes('Postgres'));

if (errors.length) console.log(`[questions]`, errors);
check('no errors in either page', errors.length === 0);
await browser.close();
log('done');
