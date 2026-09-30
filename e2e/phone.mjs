// The iPhone app on its own: link with a QR link, follow a chat started on
// the Mac, continue it, answer an approval, open the sheets, unlink.
import { devices } from 'playwright';
import { API, launch, ok, owner, suite, useFakeModel } from './lib.mjs';

const { log, shot, check, watch, errors } = suite('phone');
const mac = await owner();
await useFakeModel(mac);
const pairing = await ok(await mac.post('/api/v1/devices/pairing'));
log('pairing code', pairing.code);

const browser = await launch();
const context = await browser.newContext({ ...devices['iPhone 15'], baseURL: API });
const page = await context.newPage();
watch(page, 'phone');

await page.goto(`/m/?pair=${pairing.code}`);
await page.getByRole('heading', { name: 'Add to Home Screen' }).waitFor();
await page.screenshot({ path: shot('01-install') });
await page.getByText('Use in Safari').click();
await page.getByRole('heading', { name: 'Chats' }).waitFor();
await page.locator('.status-live').waitFor();
await page.screenshot({ path: shot('02-chats') });
check('the linking code is gone from the address', !page.url().includes('pair='));

// The Mac starts a conversation; the phone sees it arrive live.
const thread = await ok(await mac.post('/api/v1/threads', { data: { bot_id: 'bot-claude-1' } }));
await ok(await mac.post(`/api/v1/threads/${thread.id}/messages`, { data: { text: 'Help me plan the Open Dots iPhone launch' } }));
await page.locator('.continue-card .state-blue').waitFor();
await page.screenshot({ path: shot('03-live-from-mac') });
await page.locator('.continue-card .state-blue').waitFor({ state: 'detached', timeout: 15000 });
await page.screenshot({ path: shot('04-continue-card') });

// Continue it on the phone.
await page.locator('.continue-card').click();
await page.locator('.bubble-bot').first().waitFor();
await page.locator('.pill textarea').fill('Great, continuing on my phone now');
await page.locator('.send-btn').click();
await page.locator('.handoff').waitFor();
await page.locator('.bubble-bot.streaming').waitFor();
await page.waitForTimeout(900);
await page.screenshot({ path: shot('05-streaming') });
await page.locator('.bubble-bot.streaming').waitFor({ state: 'detached', timeout: 15000 });
await page.screenshot({ path: shot('06-reply-done') });

const detail = await ok(await mac.get(`/api/v1/threads/${thread.id}`));
const origins = detail.messages.map((message) => `${message.sender}:${message.origin || '-'}`).join(' ');
check('the Mac records who wrote what', origins === 'user:Computer bot:- user:iPhone bot:-');

// An action that needs approval, answered on the phone.
await page.locator('.pill textarea').fill('/workspace list .');
await page.locator('.send-btn').click();
await page.locator('.step-actions').waitFor();
await page.screenshot({ path: shot('07-approval') });
await page.getByRole('button', { name: 'Allow', exact: true }).click();
await page.locator('.step-actions').waitFor({ state: 'detached' });
await page.locator('.step-done').waitFor();
await page.locator('.bubble-bot.streaming').waitFor({ state: 'detached', timeout: 15000 });
await page.screenshot({ path: shot('08-approved') });

// New chat sheet and settings sheet.
await page.getByRole('button', { name: 'Chats' }).click();
await page.getByRole('button', { name: 'New chat' }).click();
await page.locator('.sheet-layer.open').waitFor();
await page.waitForTimeout(450);
await page.screenshot({ path: shot('09-new-chat') });
await page.locator('.sheet-layer').click({ position: { x: 20, y: 40 } });
await page.waitForTimeout(450);
await page.locator('.status').click();
await page.waitForTimeout(450);
await page.screenshot({ path: shot('10-settings') });

// Unlink, then relaunch from the old linking address (as the Home Screen app
// would): the used code must not be tried again.
page.on('dialog', (dialog) => dialog.accept());
await page.getByRole('button', { name: 'Unlink this iPhone' }).click();
await page.locator('#pair-code').waitFor();
await page.goto(`/m/?pair=${pairing.code}`);
await page.locator('#pair-code').waitFor();
check('a used linking code shows a clean link screen', (await page.locator('.error').count()) === 0);
check('no errors in the page', errors.length === 0 || (log(errors), false));
await browser.close();
await mac.dispose();
