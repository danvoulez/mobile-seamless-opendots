// Open Dots on iPhone.
//
// The conversations live on the computer running Open Dots. This page is
// served by that computer and continues them: the same chats, replies as they
// stream, the same approval requests. It talks to nothing else.

import { renderMarkdown, stripMarkdown } from './markdown.js';

// ------------------------------------------------------------------ helpers

const SVG_NS = 'http://www.w3.org/2000/svg';

function h(tag, props, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value == null || value === false) continue;
    if (key === 'class') el.className = value;
    else if (key.startsWith('on')) el.addEventListener(key.slice(2), value);
    else if (key === 'html') el.innerHTML = value; // only ever markdown.js output
    else el.setAttribute(key, value === true ? '' : value);
  }
  el.append(...children.flat().filter((child) => child != null && child !== false));
  return el;
}

function s(tag, attrs, ...children) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs || {})) el.setAttribute(key, value);
  el.append(...children);
  return el;
}

// Feather icons (MIT), the set the Mac client uses through react-icons.
const ICONS = {
  plus: [['line', { x1: 12, y1: 5, x2: 12, y2: 19 }], ['line', { x1: 5, y1: 12, x2: 19, y2: 12 }]],
  back: [['polyline', { points: '15 18 9 12 15 6' }]],
  chevron: [['polyline', { points: '9 18 15 12 9 6' }]],
  send: [['line', { x1: 12, y1: 19, x2: 12, y2: 5 }], ['polyline', { points: '5 12 12 5 19 12' }]],
  x: [['line', { x1: 18, y1: 6, x2: 6, y2: 18 }], ['line', { x1: 6, y1: 6, x2: 18, y2: 18 }]],
  check: [['polyline', { points: '20 6 9 17 4 12' }]],
  shield: [['path', { d: 'M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z' }]],
  terminal: [['polyline', { points: '4 17 10 11 4 5' }], ['line', { x1: 12, y1: 19, x2: 20, y2: 19 }]],
  search: [['circle', { cx: 11, cy: 11, r: 8 }], ['line', { x1: 21, y1: 21, x2: 16.65, y2: 16.65 }]],
  share: [['path', { d: 'M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8' }], ['polyline', { points: '16 6 12 2 8 6' }], ['line', { x1: 12, y1: 2, x2: 12, y2: 15 }]],
  add: [['rect', { x: 3, y: 3, width: 18, height: 18, rx: 2, ry: 2 }], ['line', { x1: 12, y1: 8, x2: 12, y2: 16 }], ['line', { x1: 8, y1: 12, x2: 16, y2: 12 }]],
  monitor: [['rect', { x: 2, y: 3, width: 20, height: 14, rx: 2, ry: 2 }], ['line', { x1: 8, y1: 21, x2: 16, y2: 21 }], ['line', { x1: 12, y1: 17, x2: 12, y2: 21 }]],
  clock: [['circle', { cx: 12, cy: 12, r: 10 }], ['polyline', { points: '12 6 12 12 16 14' }]],
  minus: [['line', { x1: 5, y1: 12, x2: 19, y2: 12 }]],
};

function icon(name, cls = 'icon') {
  return s('svg', {
    viewBox: '0 0 24 24', class: cls, 'aria-hidden': 'true', fill: 'none', stroke: 'currentColor',
    'stroke-width': 2, 'stroke-linecap': 'round', 'stroke-linejoin': 'round',
  }, ...ICONS[name].map(([tag, attrs]) => s(tag, attrs)));
}

const MASCOT_PATH = 'M 50 12 C 60 12, 88 65, 84 76 C 80 87, 20 87, 16 76 C 12 65, 40 12, 50 12 Z';

function mascot(type = 'blue', size = 'md') {
  if (type === 'warning') {
    return h('div', { class: `mascot mascot-${size} mascot-warning` }, h('span', null, '!'));
  }
  return h('div', { class: `mascot mascot-${size}` }, s('svg', { viewBox: '0 0 100 100' },
    s('path', { d: MASCOT_PATH, fill: `url(#od-grad-${type})` }),
    s('circle', { cx: 43, cy: 52, r: 7, fill: '#ffffff' }),
    s('circle', { cx: 41, cy: 52, r: 3.5, fill: '#0f172a' }),
    s('circle', { cx: 40, cy: 50, r: 1.2, fill: '#ffffff' }),
    s('circle', { cx: 62, cy: 54, r: 6, fill: '#ffffff' }),
    s('circle', { cx: 60, cy: 54, r: 3, fill: '#0f172a' }),
    s('circle', { cx: 59, cy: 53, r: 1, fill: '#ffffff' }),
  ));
}

function typingDots(extra = '') {
  return h('span', { class: `dots ${extra}`, 'aria-label': 'Replying' }, h('i'), h('i'), h('i'));
}

const clockFormat = new Intl.DateTimeFormat('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });

function parseTime(value) {
  const date = value ? new Date(value) : null;
  return date && !Number.isNaN(date.getTime()) ? date : null;
}

function clock(value) {
  const date = parseTime(value);
  return date ? clockFormat.format(date) : '';
}

function isSameDay(a, b) {
  return a.toDateString() === b.toDateString();
}

function listTime(value) {
  const date = parseTime(value);
  if (!date) return '';
  const now = new Date();
  if (isSameDay(date, now)) return clockFormat.format(date);
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (isSameDay(date, yesterday)) return 'Yesterday';
  if (now - date < 6 * 86400000) return date.toLocaleDateString('en-US', { weekday: 'short' });
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function dayLabel(value) {
  const date = parseTime(value) || new Date();
  const now = new Date();
  if (isSameDay(date, now)) return 'Today';
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (isSameDay(date, yesterday)) return 'Yesterday';
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

function ago(value) {
  const date = parseTime(value);
  if (!date) return '';
  const minutes = Math.round((Date.now() - date) / 60000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  return hours < 24 ? `${hours}h ago` : listTime(value);
}

const storage = {
  get(key) {
    try { return JSON.parse(localStorage.getItem(key)); } catch { return null; }
  },
  set(key, value) {
    try {
      localStorage.setItem(key, JSON.stringify(value));
      return true;
    } catch {
      return false; // private mode, or full
    }
  },
  remove(key) {
    try { localStorage.removeItem(key); } catch { /* private mode */ }
  },
};

// ---------------------------------------------------------------------- API

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function api(path, { method = 'GET', body, form } = {}) {
  let response;
  try {
    response = await fetch(`/api/v1${path}`, {
      method,
      credentials: 'same-origin',
      cache: 'no-store',
      headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
      body: form ?? (body !== undefined ? JSON.stringify(body) : undefined),
    });
  } catch {
    throw new ApiError(`Can't reach ${state.computer}.`, 0);
  }
  const data = await response.json().catch(() => ({}));
  if (response.status === 401) {
    if (state.phase === 'app') unlinked();
    throw new ApiError('This iPhone is no longer linked.', 401);
  }
  if (!response.ok) {
    const detail = Array.isArray(data.detail) ? data.detail.map((item) => item.msg).join(' ') : data.detail;
    throw new ApiError(detail || 'Something went wrong.', response.status);
  }
  return data;
}

// -------------------------------------------------------------------- state

const cache = storage.get('od:cache') || {};

const state = {
  phase: 'boot', // boot | pair | app
  computer: cache.computer || 'your Mac',
  computerKind: 'Mac', // as used mid-sentence: "your Mac", "your computer"
  device: cache.device || null,
  connection: 'connecting', // connecting | live | reconnecting
  bots: cache.bots || [],
  threads: cache.threads || [],
  search: '',
  chat: null, // { threadId, botId, thread, messages, turn, loading }
  composer: { text: '', image: null },
  drafts: new Map(),
  approvalsBusy: new Set(),
};

function saveCache() {
  storage.set('od:cache', {
    computer: state.computer,
    device: state.device,
    bots: state.bots,
    threads: state.threads.slice(0, 50),
  });
}

function botFor(botId) {
  return state.bots.find((bot) => bot.id === botId);
}

// Same assignment as the Mac sidebar: alternate blue and pink by roster order.
function avatarType(botId) {
  return state.bots.findIndex((bot) => bot.id === botId) % 2 === 1 ? 'pink' : 'blue';
}

function threadTitle(thread) {
  return thread?.title || botFor(thread?.bot_id)?.name || 'New chat';
}

function byNewest(a, b) {
  return (parseTime(b.updated_at) || 0) - (parseTime(a.updated_at) || 0);
}

function upsertThread(summary) {
  const index = state.threads.findIndex((thread) => thread.id === summary.id);
  if (index >= 0) state.threads[index] = summary;
  else state.threads.push(summary);
  state.threads.sort(byNewest);
  if (state.chat?.threadId === summary.id) {
    state.chat.thread = summary;
    schedule(renderChatHeader);
  }
  schedule(renderList);
}

function upsertMessage(message) {
  const chat = state.chat;
  const index = chat.messages.findIndex((item) => item.id === message.id
    || (message.client_id && item.client_id === message.client_id));
  if (index >= 0) chat.messages[index] = message;
  else chat.messages.push(message);
  schedule(renderMessages);
}

// Batch DOM work into one frame; streaming sends many small updates.
const pendingRenders = new Set();
let frame = 0;

function schedule(...renders) {
  renders.forEach((render) => pendingRenders.add(render));
  if (frame) return;
  frame = requestAnimationFrame(() => {
    frame = 0;
    const renders = [...pendingRenders];
    pendingRenders.clear();
    renders.forEach((render) => render());
  });
}

// ------------------------------------------------------------------ outbox

// Everything you send goes through here. While the Mac is away, messages (and
// new chats) wait, survive the app closing, and go out once it's back.
let outbox = (storage.get('od:outbox') || []).map((item) => ({ ...item, status: 'waiting' }));
let flushing = false;
let flushAgain = false;

function saveOutbox() {
  const items = outbox.map(({ status, ...item }) => item);
  if (storage.set('od:outbox', items)) return;
  // Photos can outgrow the browser's storage (about 5 MB). Keep every
  // message's text at least; the photos stay in memory while the app is open.
  storage.set('od:outbox', items.map((item) => (
    item.imageUrl?.startsWith('data:') ? { ...item, imageUrl: null, photoLost: true } : item
  )));
}

// After a restart, say so if a waiting photo couldn't be kept.
function reportLostPhotos() {
  if (!outbox.some((item) => item.photoLost)) return;
  outbox = outbox.filter((item) => item.text.trim() || !item.photoLost);
  outbox.forEach((item) => delete item.photoLost);
  saveOutbox();
  toast(`A photo you added while your ${state.computerKind} was away couldn't be kept.`);
}

const isLocal = (threadId) => String(threadId || '').startsWith('local-');

function queuedFor(threadId) {
  return outbox.filter((item) => (item.threadId || item.localId) === threadId);
}

function titleFrom(text) {
  const line = (text || '').split('\n').map((part) => part.trim()).find(Boolean) || '';
  return line.length > 60 ? `${line.slice(0, 59).trimEnd()}…` : line || 'Photo';
}

// New chats that exist only here until the Mac creates them.
function localThreads() {
  const threads = new Map();
  for (const item of outbox) {
    if (item.threadId || threads.has(item.localId)) continue;
    threads.set(item.localId, {
      id: item.localId,
      bot_id: item.botId,
      title: titleFrom(item.text),
      updated_at: item.createdAt,
      last_message: { sender: 'user', text: item.text, created_at: item.createdAt, has_image: Boolean(item.imageUrl) },
      status: 'idle',
    });
  }
  return [...threads.values()];
}

function allThreads() {
  return [...localThreads(), ...state.threads].sort(byNewest);
}

function threadBusy(threadId) {
  const status = state.threads.find((thread) => thread.id === threadId)?.status;
  return status === 'running' || status === 'waiting';
}

// A chat started on the phone gets its real id from the Mac's first reply.
function adoptThread(item, thread) {
  for (const other of outbox) {
    if (other.localId === item.localId) other.threadId = thread.id;
  }
  saveOutbox();
  upsertThread(thread);
  if (state.chat?.threadId === item.localId) {
    state.chat.threadId = thread.id;
    state.chat.thread = thread;
  }
}

async function flush() {
  if (state.phase !== 'app' || !outbox.length) return;
  if (flushing) {
    flushAgain = true; // for example, a reply ended while this pass was sending
    return;
  }
  flushing = true;
  try {
    do {
      flushAgain = false;
    } while (await sendWaiting() && flushAgain && outbox.length);
  } finally {
    flushing = false;
  }
}

// One pass over the outbox. Returns false when the Mac can't be reached.
async function sendWaiting() {
  for (const item of [...outbox]) {
    if (!outbox.includes(item)) continue;
    if (item.threadId && threadBusy(item.threadId)) continue; // goes out when the reply ends
    item.status = 'sending';
    schedule(renderMessages);
    try {
      // Safe to repeat: the Mac recognizes the message by its client id.
      const result = await rpc('messages.send', {
        thread_id: item.threadId || null,
        bot_id: item.threadId ? null : item.botId,
        text: item.text,
        image_url: item.imageUrl || null,
        client_id: item.clientId,
      });
      if (!item.threadId) adoptThread(item, result.thread);
      outbox = outbox.filter((other) => other !== item);
      saveOutbox();
      const chat = state.chat;
      if (chat?.threadId === result.thread.id) {
        upsertMessage(result.message);
        if (result.duplicate) loadChat(chat.threadId);
        else if (!chat.turn || chat.turn.botMsgId !== result.turn.botMsgId) chat.turn = result.turn;
        schedule(renderChatHeader);
      }
    } catch (error) {
      item.status = 'waiting';
      if (error.status === 0) {
        markTrouble();
        return false; // the Mac is away; everything waits for the reconnect
      }
      if (error.status === 409 || error.status === 401) continue;
      // Refused for good (for example, the chat was deleted): give the text back.
      outbox = outbox.filter((other) => other !== item);
      saveOutbox();
      if (state.chat && (state.chat.threadId === item.threadId || state.chat.threadId === item.localId) && !els.textarea.value) {
        els.textarea.value = item.text;
        state.composer.text = item.text;
        autosize();
      }
      toast(error.message);
    } finally {
      schedule(renderMessages, renderList, renderChatHeader);
    }
  }
  return true;
}

// ---------------------------------------------------------------- viewport

// Keep the layout the size of the visible area so the composer rides on top
// of the keyboard in Safari and in the Home Screen app.
function syncViewport() {
  const viewport = window.visualViewport;
  const height = viewport ? viewport.height : window.innerHeight;
  document.documentElement.style.setProperty('--app-height', `${Math.round(height)}px`);
  if (viewport && viewport.offsetTop > 0) window.scrollTo(0, 0);
}

const isStandalone = () => window.navigator.standalone === true
  || window.matchMedia('(display-mode: standalone)').matches;
const isIOS = () => /iPhone|iPad|iPod/.test(navigator.userAgent)
  || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);

// ------------------------------------------------------------------- toasts

let toastTimer = 0;

function toast(message) {
  let el = document.querySelector('.toast');
  if (!el) {
    el = h('div', { class: 'toast', role: 'status' });
    document.body.append(el);
  }
  el.textContent = message;
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 3200);
}

// ---------------------------------------------------------------- pairing

const root = document.getElementById('app');

function normalizeCode(value) {
  const cleaned = String(value || '').replace(/[\s-]/g, '').toUpperCase();
  return /^[A-HJ-NP-Z2-9]{8}$/.test(cleaned) ? `${cleaned.slice(0, 4)}-${cleaned.slice(4)}` : null;
}

function renderPair({ mode = 'enter', code = '', error = '' } = {}) {
  state.phase = 'pair';
  const kind = state.computerKind;
  let body;

  if (mode === 'install') {
    body = [
      h('h2', null, 'Add to Home Screen'),
      h('ol', { class: 'steps' },
        h('li', null, h('span', { class: 'install-icon' }, icon('share')), h('span', null, 'Tap ', h('b', null, 'Share'))),
        h('li', null, h('span', { class: 'install-icon' }, icon('add')), h('span', null, 'Tap ', h('b', null, 'Add to Home Screen'))),
        h('li', null, h('span', { class: 'install-icon' }, mascot('blue', 'xs')), h('span', null, 'Open it from your Home Screen')),
      ),
      h('button', { class: 'btn-text', type: 'button', onclick: () => link(code) }, 'Use in Safari'),
    ];
  } else if (mode === 'linking') {
    body = [
      h('div', { class: 'linking' }, typingDots('dots-lg'), h('p', null, `Connecting to your ${kind}…`)),
    ];
  } else {
    const input = h('input', {
      class: 'code-input', id: 'pair-code', name: 'code', value: code, maxlength: 9, required: true,
      placeholder: 'XXXX-XXXX', autocomplete: 'one-time-code', autocapitalize: 'characters',
      autocorrect: 'off', spellcheck: 'false', enterkeyhint: 'go', 'aria-label': 'Code',
    });
    input.addEventListener('input', () => {
      const raw = input.value.replace(/[^a-zA-Z0-9]/g, '').toUpperCase().slice(0, 8);
      input.value = raw.length > 4 ? `${raw.slice(0, 4)}-${raw.slice(4)}` : raw;
    });
    body = [
      h('h2', null, 'Link this iPhone'),
      h('p', { class: 'muted' }, `On your ${kind}, choose `, h('b', null, 'Continue on iPhone'), '. Then scan the code or type it here.'),
      h('form', {
        class: 'pair-form',
        onsubmit: (event) => {
          event.preventDefault();
          const normalized = normalizeCode(input.value);
          if (!normalized) {
            renderPair({ mode: 'enter', code: input.value, error: `Enter the 8-character code from your ${kind}.` });
            return;
          }
          link(normalized);
        },
      },
      input,
      error ? h('p', { class: 'error', role: 'alert' }, error) : null,
      h('button', { class: 'btn-primary', type: 'submit' }, 'Link')),
    ];
  }

  root.className = 'app phase-pair';
  root.replaceChildren(h('main', { class: 'pair' },
    h('div', { class: 'pair-hero' },
      mascot('blue', 'xl'),
      h('h1', null, 'Open Dots'),
      h('p', null, `Your ${kind} conversations, right where you left them.`)),
    h('section', { class: 'window' },
      h('div', { class: 'window-bar', 'aria-hidden': 'true' }, h('i', { class: 'light red' }), h('i', { class: 'light yellow' }), h('i', { class: 'light green' })),
      h('div', { class: 'window-body' }, ...body)),
    h('p', { class: 'pair-foot' }, `Everything stays on your ${kind}. No cloud in between.`),
  ));
}

// The Home Screen app keeps its start address, linking code included, so
// remember codes once tried and don't offer them again on later launches.
function codeSpent(code) {
  return (storage.get('od:spent-codes') || []).includes(code);
}

function spendCode(code) {
  storage.set('od:spent-codes', [...(storage.get('od:spent-codes') || []), code].slice(-10));
}

async function link(code) {
  renderPair({ mode: 'linking' });
  spendCode(code);
  try {
    const result = await api('/devices/pair', { method: 'POST', body: { code } });
    state.device = result.device;
    state.computer = result.computer_name || state.computer;
    history.replaceState(null, '', '/m/');
    startApp();
  } catch (error) {
    const message = error.status === 0 ? `Can't reach your ${state.computerKind}. Is it on the same Wi-Fi?` : error.message;
    renderPair({ mode: 'enter', error: message });
  }
}

function unlinked() {
  disconnect();
  storage.remove('od:cache');
  storage.remove('od:outbox');
  outbox = [];
  state.threads = [];
  state.chat = null;
  state.device = null;
  closeSheet();
  renderPair({ mode: 'enter', error: `This iPhone was unlinked. Get a new code on your ${state.computerKind} to link it again.` });
}

// ------------------------------------------------------------ app skeleton

const els = {};

function buildApp() {
  els.status = h('button', { class: 'status', type: 'button', onclick: openSettings });
  els.search = h('input', {
    class: 'search-input', type: 'search', placeholder: 'Search', 'aria-label': 'Search chats',
    autocomplete: 'off', autocorrect: 'off', enterkeyhint: 'search',
  });
  els.search.addEventListener('input', () => {
    state.search = els.search.value;
    schedule(renderList);
  });
  els.listBody = h('div', { class: 'list-body' });
  els.list = h('section', { class: 'screen screen-list', 'aria-label': 'Chats' },
    h('header', { class: 'list-header' },
      h('div', { class: 'list-bar' },
        els.status,
        h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'New chat', onclick: openNewChat }, icon('plus'))),
      h('h1', { class: 'large-title' }, 'Chats'),
      h('label', { class: 'search' }, icon('search', 'icon search-icon'), els.search)),
    els.listBody);

  els.chatTitle = h('div', { class: 'chat-title' });
  els.scroller = h('div', { class: 'chat-body' });
  els.messages = h('div', { class: 'messages' });
  els.scroller.append(els.messages);

  els.file = h('input', { type: 'file', accept: 'image/*', class: 'hidden', 'aria-hidden': 'true', tabindex: '-1' });
  els.file.addEventListener('change', pickImage);
  els.imageChip = h('div', { class: 'image-chip hidden' });
  els.textarea = h('textarea', { rows: 1, placeholder: 'Message', 'aria-label': 'Message', enterkeyhint: 'enter' });
  els.textarea.addEventListener('input', () => {
    state.composer.text = els.textarea.value;
    state.drafts.set(draftKey(), els.textarea.value);
    autosize();
    renderComposer();
  });
  els.textarea.addEventListener('focus', () => setTimeout(() => stickToBottom(true), 250));
  els.send = h('button', { class: 'send-btn', type: 'submit', 'aria-label': 'Send' }, icon('send'));
  els.composer = h('form', { class: 'composer', onsubmit: (event) => { event.preventDefault(); send(); } },
    els.imageChip,
    h('div', { class: 'pill' },
      h('button', { class: 'attach-btn', type: 'button', 'aria-label': 'Add photo', onclick: () => els.file.click() }, icon('plus')),
      els.textarea,
      els.send),
    els.file);

  els.chat = h('section', { class: 'screen screen-chat', 'aria-label': 'Chat' },
    h('header', { class: 'chat-header' },
      h('button', { class: 'back-btn', type: 'button', onclick: () => history.back() }, icon('back'), h('span', null, 'Chats')),
      els.chatTitle),
    els.scroller,
    els.composer);

  els.sheetLayer = h('div', { class: 'sheet-layer', onclick: (event) => { if (event.target === els.sheetLayer) closeSheet(); } });

  root.className = 'app phase-app';
  root.replaceChildren(els.list, els.chat, els.sheetLayer);
  enableSwipeBack();
}

function startApp() {
  state.phase = 'app';
  buildApp();
  renderList();
  connect();
  reportLostPhotos();
}

// -------------------------------------------------------------- chat list

// Connected is the normal state. Reconnecting is shown calmly and never needs
// a tap: the app keeps trying on its own.
function renderStatus() {
  const label = state.connection === 'reconnecting' ? 'Reconnecting…' : state.computer;
  els.status.className = `status status-${state.connection}`;
  els.status.replaceChildren(h('i', { class: 'status-dot' }), h('span', null, label));
  els.status.setAttribute('aria-label', `${label}. Connection details`);
}

function previewLine(thread) {
  if (thread.status === 'waiting') return h('span', { class: 'state state-amber' }, icon('shield', 'icon icon-xs'), 'Needs your approval');
  if (thread.status === 'running') return h('span', { class: 'state state-blue' }, typingDots('dots-sm'), 'Replying…');
  if (queuedFor(thread.id).some((item) => item.status === 'waiting')) {
    return h('span', { class: 'state' }, icon('clock', 'icon icon-xs'), 'Waiting to send');
  }
  const message = thread.last_message;
  if (!message) return 'New chat';
  const text = stripMarkdown(message.text) || (message.has_image ? 'Photo' : '');
  const bot = botFor(thread.bot_id);
  const prefix = message.sender === 'user' ? 'You: ' : (thread.title && bot ? `${bot.name}: ` : '');
  return prefix + text;
}

function threadRow(thread) {
  return h('button', { class: 'row', type: 'button', onclick: () => openThread(thread.id) },
    mascot(avatarType(thread.bot_id), 'md'),
    h('div', { class: 'row-main' },
      h('div', { class: 'row-top' },
        h('span', { class: 'row-title' }, threadTitle(thread)),
        h('span', { class: 'row-time' }, listTime(thread.updated_at))),
      h('div', { class: 'row-sub' }, previewLine(thread))));
}

// The Handoff moment: the chat that was just active, one tap away.
function continueCard(thread) {
  const from = thread.last_origin;
  const elsewhere = from && from !== state.device?.name;
  return h('button', { class: 'continue-card', type: 'button', onclick: () => openThread(thread.id) },
    h('div', { class: 'continue-label' },
      h('i', { class: `pip${thread.status !== 'idle' ? ' live' : ''}` }),
      h('span', null, elsewhere ? `Continue from ${from}` : 'Continue'),
      h('span', { class: 'continue-when' }, ago(thread.updated_at))),
    h('div', { class: 'continue-main' },
      mascot(avatarType(thread.bot_id), 'md'),
      h('div', { class: 'row-main' },
        h('div', { class: 'continue-title' }, threadTitle(thread)),
        h('div', { class: 'continue-sub' }, previewLine(thread))),
      icon('chevron', 'icon continue-chevron')));
}

function renderList() {
  if (state.phase !== 'app') return;
  renderStatus();
  const query = state.search.trim().toLowerCase();
  const threads = allThreads().filter((thread) => !query
    || threadTitle(thread).toLowerCase().includes(query)
    || (thread.last_message?.text || '').toLowerCase().includes(query)
    || (botFor(thread.bot_id)?.name || '').toLowerCase().includes(query));

  const children = [];
  const [first] = threads;
  const recent = first && (first.status !== 'idle'
    || Date.now() - (parseTime(first.updated_at) || 0) < 30 * 60000);
  if (!query && recent && first.last_message) {
    children.push(continueCard(first));
    if (threads.length > 1) children.push(h('div', { class: 'section-label' }, 'Recent'));
    children.push(...threads.slice(1).map(threadRow));
  } else {
    children.push(...threads.map(threadRow));
  }

  if (!threads.length) {
    children.push(h('div', { class: 'empty' },
      mascot('blue', 'lg'),
      h('p', { class: 'empty-title' }, query ? 'No matches' : 'No chats yet'),
      query ? null : h('p', { class: 'muted' }, `Start one here or on your ${state.computerKind}.`)));
  }
  els.listBody.replaceChildren(...children);
}

// ------------------------------------------------------------ navigation

function showChat() {
  els.messages.replaceChildren();
  messageNodes.clear();
  state.composer = { text: state.drafts.get(draftKey()) || '', image: null };
  els.textarea.value = state.composer.text;
  autosize();
  renderChatHeader();
  renderMessages();
  renderComposer();
  root.classList.add('in-chat');
  if (history.state?.chat !== true) history.pushState({ chat: true }, '');
}

function closeChat() {
  state.chat = null;
  root.classList.remove('in-chat');
  els.textarea.blur();
  schedule(renderList);
}

window.addEventListener('popstate', () => {
  if (state.phase === 'app' && state.chat) closeChat();
});

function openThread(threadId) {
  const thread = allThreads().find((item) => item.id === threadId) || null;
  const local = isLocal(threadId);
  state.chat = { threadId, botId: thread?.bot_id, thread, messages: [], turn: null, loading: !local };
  showChat();
  if (!local) loadChat(threadId);
}

function openDraft(botId) {
  closeSheet();
  state.chat = { threadId: null, botId, thread: null, messages: [], turn: null, loading: false };
  showChat();
  setTimeout(() => els.textarea.focus(), 350);
}

// Streaming events can ask for a reload many times a second (for example when
// a chat is opened mid-reply); only one runs at a time, plus one more if
// something asked again meanwhile.
let chatLoad = null; // { threadId, again, done }

function loadChat(threadId) {
  if (chatLoad?.threadId === threadId) {
    chatLoad.again = true;
    return chatLoad.done;
  }
  const load = { threadId, again: false };
  chatLoad = load;
  load.done = (async () => {
    try {
      do {
        load.again = false;
        await fetchChat(threadId);
      } while (load.again && state.chat?.threadId === threadId);
    } finally {
      if (chatLoad === load) chatLoad = null;
    }
  })();
  return load.done;
}

async function fetchChat(threadId) {
  try {
    const detail = await rpc('threads.get', { thread_id: threadId });
    if (state.chat?.threadId === threadId) applySnapshot(detail);
  } catch (error) {
    if (state.chat?.threadId !== threadId) return;
    if (error.status === 404) {
      history.back();
      toast('This chat was deleted.');
    } else if (error.status !== 401) {
      state.chat.loading = false;
      schedule(renderMessages);
    }
  }
}

function applySnapshot(detail) {
  const chat = state.chat;
  let turn = detail.turn;
  // Deltas that arrived while the snapshot was loading may be ahead of it.
  if (turn && chat.turn?.botMsgId === turn.botMsgId && chat.turn.text.length > turn.text.length) {
    turn = { ...turn, text: chat.turn.text };
  }
  // Keep anything newer than the snapshot (it may have loaded while sending).
  const known = new Set(detail.messages.map((message) => message.id));
  const lastAt = parseTime(detail.messages.at(-1)?.created_at) || 0;
  const newer = chat.messages.filter((message) => !known.has(message.id) && (parseTime(message.created_at) || 0) > lastAt);
  chat.messages = [...detail.messages, ...newer];
  chat.turn = turn;
  chat.thread = detail.thread;
  chat.botId = detail.thread.bot_id;
  chat.loading = false;
  upsertThread(detail.thread);
  schedule(renderChatHeader, renderMessages, renderComposer);
}

// ------------------------------------------------------------ chat screen

function renderChatHeader() {
  const chat = state.chat;
  if (!chat) return;
  const bot = botFor(chat.botId);
  const title = chat.thread?.title || bot?.name || 'New chat';
  let subtitle = null;
  if (state.connection === 'reconnecting') {
    subtitle = h('span', { class: 'chat-sub amber' }, 'Reconnecting…');
  } else if (chat.turn?.status === 'running') {
    subtitle = chat.turn.approvals?.some((approval) => approval.status === 'pending')
      ? h('span', { class: 'chat-sub amber' }, 'Needs your approval')
      : h('span', { class: 'chat-sub blue' }, 'Replying…');
  } else if (chat.thread?.title && bot) {
    subtitle = h('span', { class: 'chat-sub' }, bot.name);
  }
  els.chatTitle.replaceChildren(
    mascot(avatarType(chat.botId), 'sm'),
    h('div', { class: 'chat-title-text' }, h('span', { class: 'chat-name' }, title), subtitle));
  els.textarea.placeholder = `Message ${bot?.name || 'Open Dots'}`;
}

const messageNodes = new Map(); // key -> { el, sig, content }

function messageItem(message) {
  const key = message.client_id || message.id;
  const time = clock(message.created_at);
  if (message.sender === 'user') {
    const note = message.queued
      ? (state.connection === 'live' ? 'Sends after this reply' : `Waiting for your ${state.computerKind}`)
      : null;
    return {
      key,
      sig: `u|${message.id}|${message.pending ? 1 : 0}|${note}|${time}`,
      build: () => h('div', { class: `msg msg-user${message.pending ? ' pending' : ''}` },
        h('div', { class: 'msg-stack' },
          h('div', { class: 'bubble bubble-user' },
            message.image_url ? h('img', { class: 'bubble-image', src: message.image_url, alt: 'Photo' }) : null,
            message.text ? h('span', { class: 'bubble-text' }, message.text) : null,
            time ? h('span', { class: 'bubble-time' }, time) : null),
          note ? h('span', { class: 'msg-note' }, icon('clock', 'icon icon-xs'), note) : null)),
    };
  }
  const isError = message.is_error || /^error:/i.test(message.text || '');
  if (isError) {
    return {
      key,
      sig: `e|${message.id}|${message.text.length}`,
      build: () => h('div', { class: 'msg msg-bot' },
        h('div', { class: 'bubble bubble-error' },
          icon('x', 'icon icon-sm'),
          h('span', null, message.text),
          time ? h('span', { class: 'bubble-time' }, time) : null)),
    };
  }
  return {
    key,
    sig: `b|${message.id}|${time}|${message.streaming ? 1 : 0}`,
    // A streaming reply only swaps its text; rebuilding would restart the entrance animation.
    content: message.text || '',
    patch: (el) => { el.querySelector('.md').innerHTML = renderMarkdown(message.text); },
    build: () => h('div', { class: 'msg msg-bot' },
      h('div', { class: `bubble bubble-bot${message.streaming ? ' streaming' : ''}` },
        h('div', { class: 'md', html: renderMarkdown(message.text) }),
        time ? h('div', { class: 'bubble-time' }, time) : null)),
  };
}

// Plain names for what an action touches.
function toolLabel(name) {
  const [family, action = ''] = String(name || '').split('.');
  if (family === 'connector') return action.startsWith('github') ? 'GitHub' : 'Apps';
  return { workspace: 'Files', search: 'Web search', computer: 'Computer' }[family] || 'Action';
}

// Each thing the assistant does in a reply is one small step: an icon, a line
// of text, and a thin rail joining it to the next, so a busy reply reads as a
// quick run of steps rather than a stack of boxes.
function stepKind(approval, event) {
  if (approval?.status === 'pending') return 'ask';
  if (approval && approval.status !== 'allow') return 'skipped';
  const status = event?.type.replace('tool.', '');
  if (!status || status === 'started') return 'working';
  return { completed: 'done', failed: 'failed' }[status] || 'skipped';
}

const STEP_ICONS = { ask: 'shield', done: 'check', failed: 'x', skipped: 'minus' };

function stepStatus(kind, approval) {
  if (kind === 'skipped') return { deny: 'Denied', expired: 'Not answered in time' }[approval?.status] || 'Skipped';
  return { ask: 'Needs your approval', working: 'Working…', done: 'Done', failed: "Didn't work" }[kind];
}

function resultDetails(event) {
  if (!event?.result) return null;
  return h('details', { class: 'step-details' },
    h('summary', null, 'Details'),
    h('pre', null, JSON.stringify(event.result, null, 2)));
}

function stepItem(key, { approval, event, preview }) {
  const kind = stepKind(approval, event);
  const label = toolLabel(approval?.tool || event?.tool);
  const title = approval?.summary || preview || label;
  const busy = approval ? state.approvalsBusy.has(approval.requestId) : false;
  return {
    key: `step-${key}`,
    sig: `${kind}|${busy}|${event?.type || ''}`,
    build: () => h('div', { class: `step step-${kind}` },
      h('span', { class: 'step-icon' }, kind === 'working' ? h('i', { class: 'spinner' }) : icon(STEP_ICONS[kind])),
      h('div', { class: 'step-main' },
        h('p', { class: 'step-title' }, title),
        h('p', { class: 'step-meta' },
          title !== label ? h('span', { class: 'step-tag' }, label) : null,
          h('span', { class: 'step-status' }, stepStatus(kind, approval))),
        event?.error ? h('p', { class: 'step-error' }, event.error) : null,
        kind === 'ask'
          ? h('div', { class: 'step-actions' },
            h('button', { class: 'btn-deny', type: 'button', disabled: busy, onclick: () => respond(approval.requestId, 'deny') }, 'Deny'),
            h('button', { class: 'btn-allow', type: 'button', disabled: busy, onclick: () => respond(approval.requestId, 'allow') }, icon('check', 'icon icon-sm'), 'Allow'))
          : null,
        resultDetails(event))),
  };
}

// One entry per action: a later event for the same action updates it in place
// (keeping what it said when it started). Matches the Mac's copy of the turn.
const KEPT_STEPS = 30;

function keepToolEvent(tools, event) {
  const index = event.requestId ? tools.findIndex((known) => known.requestId === event.requestId) : -1;
  if (index === -1) return [...tools, event].slice(-KEPT_STEPS);
  const next = [...tools];
  next[index] = { ...tools[index], ...event };
  return next;
}

// One step per action, in the order they happened; an approval and the
// action it allowed are the same step, and one still waiting comes last.
function turnItems(turn) {
  if (!turn) return [];
  const waiting = new Map((turn.approvals || []).map((approval) => [approval.requestId, approval]));
  const steps = (turn.tools || []).map((event, index) => {
    const key = event.requestId || `i${index}`;
    const approval = waiting.get(key);
    waiting.delete(key);
    return stepItem(key, { approval, event, preview: event.action?.preview });
  });
  for (const [key, approval] of waiting) steps.push(stepItem(key, { approval }));
  return steps;
}

function chatItems() {
  const chat = state.chat;
  const bot = botFor(chat.botId);
  const items = [];
  const firstDated = chat.messages.find((message) => message.created_at);
  const day = dayLabel(firstDated?.created_at);
  items.push({ key: 'day', sig: day, build: () => h('div', { class: 'day' }, day) });

  if (chat.loading && !chat.messages.length) {
    items.push({ key: 'loading', sig: '', build: () => h('div', { class: 'loading' }, typingDots()) });
    return items;
  }

  const seen = new Set(chat.messages.map((message) => message.client_id).filter(Boolean));
  const queued = queuedFor(chat.threadId)
    .filter((item) => !seen.has(item.clientId))
    .map((item) => ({
      id: item.clientId, client_id: item.clientId, sender: 'user', text: item.text, image_url: item.imageUrl,
      created_at: item.createdAt, origin: state.device?.name || 'iPhone', pending: true, queued: item.status === 'waiting',
    }));
  const messages = [...chat.messages, ...queued];
  const turn = chat.turn;
  const cards = turnItems(turn);
  let cardsPlaced = false;

  if (!messages.length && !turn) {
    items.push(messageItem({ id: 'intro', sender: 'bot', text: `Hi, I'm **${bot?.name || 'Open Dots'}**. What can I help with?` }));
  }

  let lastOrigin = null;
  for (const message of messages) {
    if (message.sender === 'user' && message.origin) {
      if (lastOrigin && message.origin !== lastOrigin) {
        const text = `Continued on ${message.origin} · ${clock(message.created_at)}`;
        items.push({ key: `handoff-${message.client_id || message.id}`, sig: text, build: () => h('div', { class: 'handoff' }, h('span', null, text)) });
      }
      lastOrigin = message.origin;
    }
    if (turn && message.id === turn.botMsgId) {
      items.push(...cards);
      cardsPlaced = true;
    }
    items.push(messageItem(message));
  }

  if (turn && !cardsPlaced) {
    items.push(...cards);
    if (turn.status === 'running') {
      if (turn.text) {
        items.push(messageItem({ id: turn.botMsgId, sender: 'bot', text: turn.text, streaming: true }));
      } else if (!turn.approvals?.some((approval) => approval.status === 'pending')) {
        items.push({
          key: 'typing', sig: avatarType(chat.botId),
          build: () => h('div', { class: 'msg msg-bot typing' }, mascot(avatarType(chat.botId), 'sm'), h('div', { class: 'typing-bubble' }, typingDots())),
        });
      }
    }
  }
  return items;
}

function nearBottom() {
  const el = els.scroller;
  return el.scrollHeight - el.scrollTop - el.clientHeight < 140;
}

function stickToBottom(force = false) {
  if (force || nearBottom()) els.scroller.scrollTop = els.scroller.scrollHeight;
}

function renderMessages() {
  if (!state.chat) return;
  const stick = nearBottom() || !messageNodes.size;
  const seen = new Set();
  let previous = null;
  for (const item of chatItems()) {
    seen.add(item.key);
    let entry = messageNodes.get(item.key);
    if (!entry || entry.sig !== item.sig) {
      const el = item.build();
      if (entry) {
        el.classList.add('settled'); // already on screen: no entrance animation
        entry.el.replaceWith(el);
      }
      entry = { el, sig: item.sig, content: item.content };
      messageNodes.set(item.key, entry);
    } else if (item.patch && entry.content !== item.content) {
      item.patch(entry.el);
      entry.content = item.content;
    }
    const expected = previous ? previous.nextSibling : els.messages.firstChild;
    if (entry.el !== expected) els.messages.insertBefore(entry.el, expected);
    previous = entry.el;
  }
  for (const [key, entry] of messageNodes) {
    if (!seen.has(key)) {
      entry.el.remove();
      messageNodes.delete(key);
    }
  }
  if (stick) stickToBottom(true);
}

// ---------------------------------------------------------------- composer

function draftKey() {
  return state.chat?.threadId || `new:${state.chat?.botId}`;
}

function autosize() {
  els.textarea.style.height = 'auto';
  els.textarea.style.height = `${Math.min(els.textarea.scrollHeight, 132)}px`;
}

function renderComposer() {
  if (!state.chat) return;
  const { text, image } = state.composer;
  // Sending never waits for the Mac: the outbox holds messages until it's back.
  els.send.disabled = !(text.trim() || image);
  els.composer.classList.toggle('multiline', els.textarea.offsetHeight > 30);

  if (!image) {
    els.imageChip.classList.add('hidden');
    els.imageChip.replaceChildren();
    return;
  }
  els.imageChip.classList.remove('hidden');
  els.imageChip.replaceChildren(
    h('img', { src: image.previewUrl, alt: 'Selected photo' }),
    h('span', { class: 'chip-name' }, 'Photo'),
    h('button', { class: 'chip-remove', type: 'button', 'aria-label': 'Remove photo', onclick: removeImage }, icon('x', 'icon icon-sm')));
}

function removeImage() {
  if (state.composer.image) URL.revokeObjectURL(state.composer.image.previewUrl);
  state.composer.image = null;
  renderComposer();
}

async function downscale(file, maxSide = 1600) {
  const url = URL.createObjectURL(file);
  try {
    const img = await new Promise((resolve, reject) => {
      const image = new Image();
      image.onload = () => resolve(image);
      image.onerror = reject;
      image.src = url;
    });
    const scale = Math.min(1, maxSide / Math.max(img.naturalWidth, img.naturalHeight));
    if (scale === 1 && file.size < 1_500_000 && /^image\/(jpeg|png|webp)$/.test(file.type)) return file;
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(img.naturalWidth * scale);
    canvas.height = Math.round(img.naturalHeight * scale);
    canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
    return await new Promise((resolve, reject) => canvas.toBlob(
      (blob) => (blob ? resolve(blob) : reject(new Error('Could not prepare the photo.'))),
      'image/jpeg', 0.85,
    ));
  } finally {
    URL.revokeObjectURL(url);
  }
}

function blobToDataUrl(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

// Prepare the photo right away; upload it now if the Mac is there, otherwise
// it travels with the message when it's sent.
function pickImage() {
  const file = els.file.files?.[0];
  els.file.value = '';
  if (!file) return;
  if (!file.type.startsWith('image/')) {
    toast('Only photos can be added.');
    return;
  }
  removeImage();
  const image = { previewUrl: URL.createObjectURL(file), url: null };
  image.ready = (async () => {
    const blob = await downscale(file).catch(() => file);
    if (state.connection === 'live') {
      try {
        const form = new FormData();
        const type = blob.type || file.type;
        form.append('file', blob, `photo.${type === 'image/png' ? 'png' : type === 'image/webp' ? 'webp' : 'jpg'}`);
        image.url = (await api('/upload', { method: 'POST', form })).url;
      } catch { /* sent with the message instead */ }
    }
    return image.url || blobToDataUrl(blob);
  })();
  state.composer.image = image;
  renderComposer();
}

async function send() {
  const chat = state.chat;
  const text = els.textarea.value;
  const image = state.composer.image;
  if (!text.trim() && !image) return;

  state.composer = { text: '', image: null };
  state.drafts.delete(draftKey());
  els.textarea.value = '';
  autosize();
  renderComposer();

  let imageUrl = null;
  if (image) {
    imageUrl = await image.ready.catch(() => null);
    URL.revokeObjectURL(image.previewUrl);
    if (!imageUrl) toast("That photo couldn't be added.");
  }
  if (!text.trim() && !imageUrl) return;

  const clientId = `c-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
  const threadId = chat.threadId && !isLocal(chat.threadId) ? chat.threadId : null;
  const localId = threadId ? null : chat.threadId || `local-${clientId}`;
  outbox.push({
    clientId, threadId, localId, botId: chat.botId, text, imageUrl, createdAt: new Date().toISOString(), status: 'waiting',
  });
  saveOutbox();
  if (!chat.threadId) chat.threadId = localId;
  schedule(renderMessages, renderList);
  stickToBottom(true);
  flush();
}

async function respond(requestId, action) {
  state.approvalsBusy.add(requestId);
  schedule(renderMessages);
  try {
    await rpc('approvals.respond', { request_id: requestId, action });
  } catch (error) {
    if (error.status === 404) toast('Already answered.');
    else if (error.status !== 401) toast(error.message);
  } finally {
    state.approvalsBusy.delete(requestId);
    schedule(renderMessages);
  }
}

// ------------------------------------------------------------------ sheets

function openSheet(...content) {
  els.sheetLayer.replaceChildren(h('div', { class: 'sheet', role: 'dialog', 'aria-modal': 'true' },
    h('div', { class: 'grabber' }), ...content));
  els.sheetLayer.classList.add('open');
  els.list.inert = true; // modal: keep VoiceOver and taps on the sheet
  els.chat.inert = true;
}

function closeSheet() {
  if (!els.sheetLayer) return;
  els.sheetLayer.classList.remove('open');
  els.list.inert = false;
  els.chat.inert = false;
}

async function openNewChat() {
  const rows = () => (state.bots.length
    ? state.bots.map((bot) => h('button', { class: 'row', type: 'button', onclick: () => openDraft(bot.id) },
      mascot(avatarType(bot.id), 'md'),
      h('div', { class: 'row-main' },
        h('div', { class: 'row-top' }, h('span', { class: 'row-title' }, bot.name)),
        h('div', { class: 'row-sub' }, bot.role || bot.description || ''))))
    : [h('p', { class: 'muted sheet-note' }, `Create assistants on your ${state.computerKind}.`)]);
  const list = h('div', { class: 'sheet-list' }, ...rows());
  openSheet(
    h('div', { class: 'sheet-head' },
      h('div', null, h('h2', null, 'New chat'), h('p', { class: 'muted' }, 'Choose an assistant')),
      h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Close', onclick: closeSheet }, icon('x'))),
    list);
  try {
    state.bots = await rpc('bots.list');
    list.replaceChildren(...rows());
  } catch { /* the saved list is shown */ }
}

function openSettings() {
  const linked = state.device?.created_at ? parseTime(state.device.created_at) : null;
  openSheet(
    h('div', { class: 'sheet-head' },
      h('div', { class: 'sheet-computer' },
        h('span', { class: 'computer-icon' }, icon('monitor')),
        h('div', null,
          h('h2', null, state.computer),
          h('p', { class: 'muted' }, state.connection === 'live' ? 'Connected' : 'Reconnecting…'))),
      h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Close', onclick: closeSheet }, icon('x'))),
    h('p', { class: 'sheet-copy' },
      `Your chats live on this ${state.computerKind}. When it's away, Open Dots keeps trying and sends what you wrote once it's back.`),
    linked ? h('p', { class: 'muted sheet-note' }, `Linked ${linked.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}`) : null,
    state.device
      ? h('button', { class: 'btn-danger', type: 'button', onclick: unlinkThisPhone }, 'Unlink this iPhone')
      : null);
}

async function unlinkThisPhone() {
  if (!window.confirm('Unlink this iPhone? You can link it again anytime.')) return;
  try {
    await api('/devices/current', { method: 'DELETE' });
  } catch (error) {
    if (error.status !== 401) {
      toast(error.message);
      return;
    }
  }
  unlinked();
}

// ------------------------------------------------------------ swipe back

function enableSwipeBack() {
  let start = null;
  els.chat.addEventListener('touchstart', (event) => {
    const touch = event.touches[0];
    start = touch.clientX < 24 && state.chat ? { x: touch.clientX, y: touch.clientY, t: Date.now(), dx: 0 } : null;
  }, { passive: true });
  els.chat.addEventListener('touchmove', (event) => {
    if (!start) return;
    const touch = event.touches[0];
    start.dx = Math.max(0, touch.clientX - start.x);
    if (Math.abs(touch.clientY - start.y) > start.dx && start.dx < 10) {
      start = null;
      return;
    }
    root.classList.add('swiping');
    els.chat.style.transform = `translateX(${start.dx}px)`;
  }, { passive: true });
  els.chat.addEventListener('touchend', () => {
    if (!start) return;
    const fast = start.dx / Math.max(1, Date.now() - start.t) > 0.5;
    const done = start.dx > window.innerWidth * 0.35 || (fast && start.dx > 40);
    root.classList.remove('swiping');
    els.chat.style.transform = '';
    start = null;
    if (done) history.back();
  });
}

// ------------------------------------------------------ staying connected

// One WebSocket to the Mac carries everything: requests (JSON-RPC 2.0) and
// live events (notifications). It works the same on the local network and
// through a tunnel such as Cloudflare Tunnel.
//
// Being connected is the normal state, and the app works to stay there: it
// reconnects on its own, notices a connection that died silently, and
// reconnects as soon as the phone wakes up or changes network.
const RETRY_MAX = 5000;
const SILENCE_LIMIT = 40000; // the Mac sends a heartbeat every 15 s
const TROUBLE_GRACE = 3000; // don't flash "Reconnecting…" for a blip
const CALL_TIMEOUT = 20000;
const CLOSE_NOT_LINKED = 4401;

let socket = null;
let retryTimer = 0;
let retryDelay = 1000;
let troubleTimer = 0;
let lastEventAt = 0;
let hiddenAt = 0;
let nextCallId = 0;
const calls = new Map(); // request id -> { resolve, reject, timer }

function setConnection(value) {
  if (state.connection === value) return;
  state.connection = value;
  schedule(renderList, renderChatHeader, renderMessages);
}

function markTrouble() {
  if (state.connection === 'reconnecting' || troubleTimer) return;
  troubleTimer = setTimeout(() => {
    troubleTimer = 0;
    setConnection('reconnecting');
  }, TROUBLE_GRACE);
}

function unreachable() {
  return new ApiError(`Can't reach ${state.computer}.`, 0);
}

// Calls in flight when the connection drops fail as "unreachable"; the
// outbox keeps what was being sent and tries again after reconnecting.
function failCalls() {
  for (const call of calls.values()) {
    clearTimeout(call.timer);
    call.reject(unreachable());
  }
  calls.clear();
}

function rpc(method, params = {}) {
  if (!socket || socket.readyState !== WebSocket.OPEN) return Promise.reject(unreachable());
  nextCallId += 1;
  const id = nextCallId;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      calls.delete(id);
      reject(unreachable());
    }, CALL_TIMEOUT);
    calls.set(id, { resolve, reject, timer });
    socket.send(JSON.stringify({ jsonrpc: '2.0', id, method, params }));
  });
}

function receive(item) {
  if (item.method === 'event') {
    handleEvent(item.params);
    return;
  }
  const call = calls.get(item.id);
  if (!call) return;
  calls.delete(item.id);
  clearTimeout(call.timer);
  if (item.error) call.reject(new ApiError(item.error.message, item.error.data?.status || 500));
  else call.resolve(item.result);
}

function disconnect() {
  clearTimeout(retryTimer);
  retryTimer = 0;
  const previous = socket;
  socket = null;
  if (previous) {
    previous.onclose = null;
    previous.close();
  }
  failCalls();
}

function connect() {
  disconnect();
  lastEventAt = Date.now();
  const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/v1/rpc`);
  socket = ws;
  ws.onmessage = (message) => {
    if (socket !== ws) return;
    lastEventAt = Date.now();
    let data;
    try { data = JSON.parse(message.data); } catch { return; }
    (Array.isArray(data) ? data : [data]).forEach(receive);
  };
  ws.onclose = (event) => {
    if (socket !== ws) return;
    socket = null;
    failCalls();
    if (event.code === CLOSE_NOT_LINKED) {
      unlinked();
      return;
    }
    markTrouble();
    retryTimer = setTimeout(connect, retryDelay);
    retryDelay = Math.min(retryDelay * 2, RETRY_MAX);
  };
}

setInterval(() => {
  if (state.phase !== 'app' || document.hidden) return;
  if (socket ? Date.now() - lastEventAt > SILENCE_LIMIT : !retryTimer) connect();
}, 5000);

document.addEventListener('visibilitychange', () => {
  if (document.hidden) {
    hiddenAt = Date.now();
    return;
  }
  // iOS drops connections in the background; reopen and catch up.
  if (state.phase === 'app' && (!socket || socket.readyState !== WebSocket.OPEN || Date.now() - hiddenAt > 3000)) connect();
});
window.addEventListener('online', () => { if (state.phase === 'app') connect(); });
window.addEventListener('pageshow', (event) => { if (event.persisted && state.phase === 'app') connect(); });

async function refreshAll() {
  try {
    const [threads, bots] = await Promise.all([rpc('threads.list'), rpc('bots.list')]);
    state.threads = threads.sort(byNewest);
    state.bots = bots;
    saveCache();
    schedule(renderList);
    if (state.chat?.threadId && !isLocal(state.chat.threadId)) await loadChat(state.chat.threadId);
    else if (state.chat) schedule(renderChatHeader, renderMessages);
  } catch { /* the connection status already says why */ }
}

function handleEvent(event) {
  const chat = state.chat;
  const inChat = chat?.threadId && event.threadId === chat.threadId;
  const turn = inChat ? chat.turn : null;

  switch (event.type) {
    case 'hello':
      clearTimeout(troubleTimer);
      troubleTimer = 0;
      retryDelay = 1000;
      if (event.computer) state.computer = event.computer;
      if (event.device) state.device = event.device;
      setConnection('live');
      refreshAll().then(flush);
      return;
    case 'heartbeat':
      return;
    case 'resync':
      refreshAll().then(flush);
      return;
    case 'thread.created':
    case 'thread.updated':
      upsertThread(event.thread);
      if (event.thread.status === 'idle' && queuedFor(event.thread.id).length) flush();
      return;
    case 'thread.deleted':
      state.threads = state.threads.filter((thread) => thread.id !== event.threadId);
      schedule(renderList);
      if (inChat) {
        history.back();
        toast('This chat was deleted.');
      }
      return;
    case 'device.unlinked':
      if (state.device && event.deviceId === state.device.id) unlinked();
      return;
    default:
      break;
  }
  if (!inChat) return;

  switch (event.type) {
    case 'message.created':
      upsertMessage(event.message);
      break;
    case 'turn.started':
      if (chat.turn?.botMsgId !== event.botMsgId || chat.turn.status !== 'running') {
        chat.turn = { turnId: event.turnId, botMsgId: event.botMsgId, model: event.model, status: 'running', text: '', approvals: [], tools: [] };
      }
      schedule(renderChatHeader, renderMessages);
      break;
    case 'content.delta': {
      if (!turn || turn.botMsgId !== event.botMsgId || event.offset > turn.text.length) {
        loadChat(chat.threadId); // joined late or missed text: reload the snapshot
        break;
      }
      if (event.offset + event.delta.length > turn.text.length) {
        turn.text = turn.text.slice(0, event.offset) + event.delta;
        schedule(renderMessages);
      }
      break;
    }
    case 'request.opened':
      if (!turn) {
        loadChat(chat.threadId);
        break;
      }
      turn.approvals = [...turn.approvals.filter((a) => a.requestId !== event.requestId), {
        requestId: event.requestId, tool: event.tool, summary: event.summary, arguments: event.arguments, status: 'pending',
      }];
      schedule(renderChatHeader, renderMessages);
      break;
    case 'request.resolved':
      if (turn) {
        turn.approvals = turn.approvals.map((a) => (a.requestId === event.requestId ? { ...a, status: event.decision } : a));
        schedule(renderChatHeader, renderMessages);
      }
      break;
    case 'turn.completed':
      if (turn) turn.status = event.ok ? 'completed' : 'failed';
      if (event.message) upsertMessage(event.message);
      schedule(renderChatHeader, renderMessages);
      break;
    default:
      if (event.type.startsWith('tool.') && turn) {
        const { threadId, ...tool } = event;
        turn.tools = keepToolEvent(turn.tools, tool);
        schedule(renderMessages);
      }
  }
}

// -------------------------------------------------------------------- boot

async function boot() {
  // A saved copy lets the app open while the computer is away (HTTPS only).
  if ('serviceWorker' in navigator && window.isSecureContext) {
    navigator.serviceWorker.register('/m/sw.js', { scope: '/m/' }).catch(() => {});
  }
  syncViewport();
  window.visualViewport?.addEventListener('resize', syncViewport);
  window.visualViewport?.addEventListener('scroll', syncViewport);
  window.addEventListener('resize', syncViewport);

  const health = await fetch('/api/v1/health', { cache: 'no-store' }).then((r) => r.json()).catch(() => null);
  if (health?.computer_kind) state.computerKind = health.computer_kind === 'Mac' ? 'Mac' : health.computer_kind.toLowerCase();
  if (!cache.computer) state.computer = `your ${state.computerKind}`;

  const linkCode = normalizeCode(new URLSearchParams(location.search).get('pair'));
  const code = linkCode && !codeSpent(linkCode) ? linkCode : null;
  try {
    const current = await api('/devices/current');
    state.device = current.device;
    state.computer = current.computer_name || state.computer;
    if (linkCode) history.replaceState(null, '', '/m/');
    startApp();
    return;
  } catch (error) {
    if (error.status === 0 && cache.computer) {
      // Linked before and the computer is away: show what we have and keep trying.
      state.connection = 'reconnecting';
      startApp();
      return;
    }
    if (error.status === 0) {
      renderPair({ mode: 'enter', code: code || '', error: `Can't reach your ${state.computerKind}. Is it on the same Wi-Fi?` });
      return;
    }
  }

  if (!code) renderPair({ mode: 'enter' });
  else if (isIOS() && !isStandalone()) renderPair({ mode: 'install', code });
  else link(code);
}

boot();
