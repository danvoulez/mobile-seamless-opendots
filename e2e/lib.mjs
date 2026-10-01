// Shared setup for the browser end-to-end suites (run them with ./run.sh).
import { mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { chromium, request } from 'playwright';

// One server serves the Mac page, the iPhone app and the API. The Mac opens it
// as localhost and the phone as 127.0.0.1, so each keeps its own cookies.
export const PORT = process.env.E2E_PORT || '4747';
export const API = process.env.E2E_API || `http://127.0.0.1:${PORT}`;
export const WEB = process.env.E2E_WEB || `http://localhost:${PORT}`;
export const TOKEN = process.env.E2E_TOKEN || 'e2e-owner-token';
export const MODEL_URL = process.env.E2E_MODEL_URL || 'http://127.0.0.1:9100/v1';
export const ROOT = fileURLToPath(new URL('..', import.meta.url));

export function suite(name) {
  const dir = `${process.env.SHOTS || fileURLToPath(new URL('./shots', import.meta.url))}/${name}`;
  mkdirSync(dir, { recursive: true });
  const errors = [];
  return {
    log: (...args) => console.log(`[${name}]`, ...args),
    shot: (file) => `${dir}/${file}.png`,
    check(label, condition) {
      if (!condition) throw new Error(`[${name}] check failed: ${label}`);
      console.log(`[${name}] ✓ ${label}`);
    },
    // Page errors and console errors, except the expected 401 after unlinking.
    watch(page, who) {
      page.on('pageerror', (error) => errors.push(`${who}: ${error.message}`));
      page.on('console', (message) => {
        if (message.type() === 'error' && !message.text().includes('401')) errors.push(`${who}: ${message.text()}`);
      });
    },
    errors,
  };
}

export function launch() {
  return chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
}

export function owner() {
  return request.newContext({ baseURL: API, extraHTTPHeaders: { Authorization: `Bearer ${TOKEN}` } });
}

export async function ok(response) {
  if (!response.ok()) throw new Error(`${response.url()} ${response.status()} ${await response.text()}`);
  return response.json();
}

export async function useFakeModel(mac) {
  await ok(await mac.post('/api/v1/settings', {
    data: { model_api_wire_api: 'responses', model_api_base_url: MODEL_URL, model_api_key: 'test-key', default_model: 'gpt-5-mini' },
  }));
}
