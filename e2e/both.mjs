// The Mac web client and the iPhone together: link by typing the code, join a
// reply midway, continue on the phone, approve on the Mac what the phone
// asked, start a chat on the phone, unlink from the Mac.
import { devices } from 'playwright';
import { API, TOKEN, WEB, launch, ok, owner, suite, useFakeModel } from './lib.mjs';

const { log, shot, check, watch, errors } = suite('both');
const api = await owner();
await useFakeModel(api);

const browser = await launch();

// ---- Mac: sign in with the owner token
const macContext = await browser.newContext({ viewport: { width: 1360, height: 860 }, deviceScaleFactor: 2 });
const mac = await macContext.newPage();
watch(mac, 'mac');
await mac.goto(`${WEB}/`);
await mac.locator('#owner-token').fill(TOKEN);
await mac.getByRole('button', { name: 'Sign in' }).click();
await mac.getByText('Continue on iPhone').waitFor();
await mac.waitForTimeout(800);
await mac.screenshot({ path: shot('01-mac-home') });

// ---- Mac: Continue on iPhone panel
await mac.getByText('Continue on iPhone').click();
await mac.getByText('Scan with your iPhone').waitFor();
await mac.locator('svg[aria-label="Linking QR code"]').waitFor();
const code = (await mac.locator('p.font-mono.text-lg').textContent()).trim();
log('code on Mac', code);
await mac.screenshot({ path: shot('02-mac-continuity') });

// ---- iPhone: open the address and type the code
const phoneContext = await browser.newContext({ ...devices['iPhone 15'] });
const phone = await phoneContext.newPage();
watch(phone, 'phone');
await phone.goto(`${API}/m`);
await phone.locator('#pair-code').waitFor();
await phone.screenshot({ path: shot('03-phone-enter-code') });
await phone.locator('#pair-code').fill(code.replace('-', '').toLowerCase());
await phone.getByRole('button', { name: 'Link', exact: true }).click();
await phone.getByRole('heading', { name: 'Chats' }).waitFor();
await mac.getByText('is linked.').waitFor();
await mac.screenshot({ path: shot('04-mac-linked') });
await mac.keyboard.press('Escape');
await mac.locator('button[title="Close"]').first().click();

// ---- Mac: a new chat with Claude Architect
await mac.locator('button[title="New Chat"]').click();
await mac.getByRole('button', { name: /Claude Architect/ }).click();
await mac.locator('textarea').fill('Draft the launch notes for Open Dots on iPhone');
await mac.locator('textarea').press('Enter');
await mac.getByText('Replying…').first().waitFor();

// ---- iPhone: the Continue card appears while the Mac's reply streams; join midway
await phone.locator('.continue-card .state-blue').waitFor();
await phone.screenshot({ path: shot('05-phone-continue-live') });
await mac.waitForTimeout(1200);
await phone.locator('.continue-card').click();
await phone.locator('.bubble-bot.streaming').waitFor();
await phone.waitForTimeout(600);
await phone.screenshot({ path: shot('06-phone-joined-midway') });
await mac.screenshot({ path: shot('07-mac-streaming') });
await phone.locator('.bubble-bot.streaming').waitFor({ state: 'detached', timeout: 20000 });
const phoneText = (await phone.locator('.bubble-bot').last().innerText()).trim();
const threads = await ok(await api.get('/api/v1/threads'));
const stored = await ok(await api.get(`/api/v1/threads/${threads[0].id}`));
check('the reply joined midway matches the stored reply', phoneText.startsWith(stored.messages.at(-1).text.split('\n')[0]));

// ---- iPhone continues; the Mac sees it live
await phone.locator('.pill textarea').fill('Add a line about approvals from the phone');
await phone.locator('.send-btn').click();
await mac.getByText('Continued on iPhone').waitFor();
await mac.getByText('Replying…').first().waitFor({ state: 'detached', timeout: 20000 });
await mac.waitForTimeout(400);
await mac.screenshot({ path: shot('08-mac-continued-on-iphone') });

// ---- An approval asked from the phone, answered on the Mac
await phone.locator('.pill textarea').fill('/workspace list .');
await phone.locator('.send-btn').click();
await phone.locator('.step-actions').waitFor();
await mac.getByRole('button', { name: 'Allow', exact: true }).waitFor();
await mac.waitForTimeout(600);
await mac.screenshot({ path: shot('09-mac-approval-from-phone') });
await mac.getByRole('button', { name: 'Allow', exact: true }).click();
await phone.locator('.step-actions').waitFor({ state: 'detached' });
await phone.locator('.step-done').waitFor();
await phone.locator('.bubble-bot.streaming').waitFor({ state: 'detached', timeout: 20000 });
await phone.screenshot({ path: shot('10-phone-approved-on-mac') });

// ---- A chat started on the iPhone shows up on the Mac
await phone.locator('.back-btn').click();
await phone.getByRole('button', { name: 'New chat' }).click();
await phone.getByRole('button', { name: /Codex Builder/ }).click();
await phone.locator('.pill textarea').fill('Started this one on my phone');
await phone.locator('.send-btn').click();
await mac.getByText('Started this one on my phone').first().waitFor();
await mac.waitForTimeout(2500);
await mac.screenshot({ path: shot('11-mac-sidebar-phone-chat') });

// ---- Settings → Updates shows the running version
await mac.locator('button[title="Settings"]').click();
await mac.getByRole('heading', { name: 'Updates' }).waitFor();
await mac.getByRole('heading', { name: 'Updates' }).scrollIntoViewIfNeeded();
await mac.screenshot({ path: shot('12-mac-updates') });
await mac.locator('button[title="Close App Settings"]').click();

// ---- Unlink from the Mac; the phone returns to the link screen
const linked = await ok(await api.get('/api/v1/devices'));
await api.delete(`/api/v1/devices/${linked[0].id}`);
await phone.getByText('This iPhone was unlinked').waitFor({ timeout: 10000 });
check('unlinking reaches the phone live', true);

check('no errors in either page', errors.length === 0 || (log(errors), false));
await browser.close();
await api.dispose();
