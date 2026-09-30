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
  alert: [['circle', { cx: 12, cy: 12, r: 10 }], ['line', { x1: 12, y1: 8, x2: 12, y2: 12 }], ['line', { x1: 12, y1: 16, x2: 12.01, y2: 16 }]],
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
    try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* private mode */ }
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
  computerKind: 'Mac',
  device: cache.device || null,
  connection: 'connecting', // connecting | live | offline
  bots: cache.bots || [],
  threads: cache.threads || [],
  search: '',
  chat: null, // { threadId, botId, thread, messages, turn, loading }
  composer: { text: '', image: null },
  sending: false,
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
  return thread?.title || botFor(thread?.bot_id)?.name || 'Conversation';
}

function sortThreads() {
  state.threads.sort((a, b) => (parseTime(b.updated_at) || 0) - (parseTime(a.updated_at) || 0));
}

function upsertThread(summary) {
  const index = state.threads.findIndex((thread) => thread.id === summary.id);
  if (index >= 0) state.threads[index] = summary;
  else state.threads.push(summary);
  sortThreads();
  if (state.chat?.threadId === summary.id) {
    state.chat.thread = summary;
    schedule(renderChatHeader, renderComposer);
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

function turnRunning() {
  return state.chat?.turn?.status === 'running';
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
      h('h2', null, 'Add Open Dots to your Home Screen'),
      h('p', { class: 'muted' }, `It opens full screen and stays linked to your ${kind}.`),
      h('ol', { class: 'steps' },
        h('li', null, h('span', { class: 'step-icon' }, icon('share')), h('span', null, 'Tap ', h('b', null, 'Share'), ' in Safari')),
        h('li', null, h('span', { class: 'step-icon' }, icon('add')), h('span', null, 'Choose ', h('b', null, 'Add to Home Screen'))),
        h('li', null, h('span', { class: 'step-icon' }, mascot('blue', 'xs')), h('span', null, 'Open ', h('b', null, 'Open Dots'), ' from your Home Screen')),
      ),
      h('button', { class: 'btn-text', type: 'button', onclick: () => link(code) }, 'Use in Safari instead'),
    ];
  } else if (mode === 'linking') {
    body = [
      h('div', { class: 'linking' }, typingDots('dots-lg'), h('p', null, `Linking with your ${kind}…`)),
    ];
  } else {
    const input = h('input', {
      class: 'code-input', id: 'pair-code', name: 'code', value: code, maxlength: 9, required: true,
      placeholder: 'XXXX-XXXX', autocomplete: 'one-time-code', autocapitalize: 'characters',
      autocorrect: 'off', spellcheck: 'false', enterkeyhint: 'go', 'aria-label': 'Linking code',
    });
    input.addEventListener('input', () => {
      const raw = input.value.replace(/[^a-zA-Z0-9]/g, '').toUpperCase().slice(0, 8);
      input.value = raw.length > 4 ? `${raw.slice(0, 4)}-${raw.slice(4)}` : raw;
    });
    body = [
      h('h2', null, 'Link this iPhone'),
      h('p', { class: 'muted' }, `On your ${kind}, open Open Dots and choose `, h('b', null, 'Continue on iPhone'), '. Scan the code with your camera, or type it here.'),
      h('form', {
        class: 'pair-form',
        onsubmit: (event) => {
          event.preventDefault();
          const normalized = normalizeCode(input.value);
          if (!normalized) {
            renderPair({ mode: 'enter', code: input.value, error: 'Codes look like K7QM-2XRP.' });
            return;
          }
          link(normalized);
        },
      },
      input,
      error ? h('p', { class: 'error', role: 'alert' }, error) : null,
      h('button', { class: 'btn-primary', type: 'submit' }, 'Link iPhone')),
    ];
  }

  root.className = 'app phase-pair';
  root.replaceChildren(h('main', { class: 'pair' },
    h('div', { class: 'pair-hero' },
      mascot('blue', 'xl'),
      h('h1', null, 'Open Dots'),
      h('p', null, `Continue your conversations from your ${kind}, right where you left them.`)),
    h('section', { class: 'window' },
      h('div', { class: 'window-bar', 'aria-hidden': 'true' }, h('i', { class: 'light red' }), h('i', { class: 'light yellow' }), h('i', { class: 'light green' })),
      h('div', { class: 'window-body' }, ...body)),
    h('p', { class: 'pair-foot' }, `Your conversations stay on your ${kind}. This iPhone talks to it directly over your network — no cloud in between.`),
  ));
}

async function link(code) {
  renderPair({ mode: 'linking' });
  try {
    const result = await api('/devices/pair', { method: 'POST', body: { code } });
    state.device = result.device;
    state.computer = result.computer_name || state.computer;
    history.replaceState(null, '', '/m/');
    startApp();
  } catch (error) {
    const message = error.status === 0
      ? `Can't reach your ${state.computerKind}. Make sure it's awake and on the same Wi-Fi.`
      : error.message;
    renderPair({ mode: 'enter', error: message });
  }
}

function unlinked() {
  source?.close();
  source = null;
  storage.remove('od:cache');
  state.threads = [];
  state.chat = null;
  state.device = null;
  closeSheet();
  renderPair({ mode: 'enter', error: 'This iPhone was unlinked. Show a new code on your Mac to link it again.' });
}

// ------------------------------------------------------------ app skeleton

const els = {};

function buildApp() {
  els.status = h('button', { class: 'status', type: 'button', onclick: openSettings });
  els.search = h('input', {
    class: 'search-input', type: 'search', placeholder: 'Search', 'aria-label': 'Search conversations',
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
      h('button', { class: 'attach-btn', type: 'button', 'aria-label': 'Attach image', onclick: () => els.file.click() }, icon('plus')),
      els.textarea,
      els.send),
    els.file);

  els.chat = h('section', { class: 'screen screen-chat', 'aria-label': 'Conversation' },
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
}

// -------------------------------------------------------------- chat list

function renderStatus() {
  const labels = {
    live: state.computer,
    connecting: 'Connecting…',
    offline: `${state.computerKind} unavailable`,
  };
  els.status.className = `status status-${state.connection}`;
  els.status.replaceChildren(h('i', { class: 'status-dot' }), h('span', null, labels[state.connection]));
  els.status.setAttribute('aria-label', `${labels[state.connection]}. Linked device settings`);
}

function previewLine(thread) {
  if (thread.status === 'waiting') return h('span', { class: 'badge badge-amber' }, 'Needs your approval');
  if (thread.status === 'running') return h('span', { class: 'live-line' }, typingDots('dots-sm'), 'Replying…');
  const message = thread.last_message;
  if (!message) return 'No messages yet';
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

// The Handoff moment: the conversation that was just active, one tap away.
function continueCard(thread) {
  const from = thread.last_origin;
  const mine = state.device?.name;
  const label = from && from !== mine ? `Continue from ${from}` : 'Pick up where you left off';
  return h('button', { class: 'continue-card', type: 'button', onclick: () => openThread(thread.id) },
    h('div', { class: 'continue-label' },
      icon(from && from !== mine ? 'monitor' : 'chevron', 'icon icon-xs'),
      h('span', null, label),
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
  const threads = state.threads.filter((thread) => !query
    || threadTitle(thread).toLowerCase().includes(query)
    || (thread.last_message?.text || '').toLowerCase().includes(query)
    || (botFor(thread.bot_id)?.name || '').toLowerCase().includes(query));

  const children = [];
  if (state.connection === 'offline') {
    children.push(h('div', { class: 'banner' },
      icon('alert', 'icon icon-sm'),
      h('div', null,
        h('b', null, `Can't reach ${state.computer}.`),
        h('span', null, ` Make sure your ${state.computerKind} is awake and on the same network.`)),
      h('button', { class: 'banner-btn', type: 'button', onclick: () => connect() }, 'Retry')));
  }

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
      h('p', { class: 'empty-title' }, query ? 'No matches' : 'No conversations yet'),
      h('p', { class: 'muted' }, query ? 'Try another word.' : `Start one here or on your ${state.computerKind}.`)));
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
  const thread = state.threads.find((item) => item.id === threadId) || null;
  state.chat = { threadId, botId: thread?.bot_id, thread, messages: [], turn: null, loading: true };
  showChat();
  loadChat(threadId);
}

function openDraft(botId) {
  closeSheet();
  state.chat = { threadId: null, botId, thread: null, messages: [], turn: null, loading: false };
  showChat();
  setTimeout(() => els.textarea.focus(), 350);
}

async function loadChat(threadId) {
  try {
    const detail = await api(`/threads/${encodeURIComponent(threadId)}`);
    if (state.chat?.threadId === threadId) applySnapshot(detail);
  } catch (error) {
    if (state.chat?.threadId !== threadId) return;
    if (error.status === 404) {
      history.back();
      toast('That conversation was deleted.');
    } else if (error.status !== 401) {
      state.chat.loading = false;
      schedule(renderMessages);
    }
  }
}

function applySnapshot(detail) {
  const chat = state.chat;
  const confirmed = new Set(detail.messages.map((message) => message.client_id).filter(Boolean));
  const unconfirmed = chat.messages.filter((message) => message.pending && !confirmed.has(message.client_id));
  chat.messages = [...detail.messages, ...unconfirmed];
  let turn = detail.turn;
  // Deltas that arrived while the snapshot was loading may be ahead of it.
  if (turn && chat.turn?.botMsgId === turn.botMsgId && chat.turn.text.length > turn.text.length) {
    turn = { ...turn, text: chat.turn.text };
  }
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
  let subtitle = h('span', { class: 'chat-sub' }, bot?.model || '');
  if (chat.turn?.status === 'running') {
    subtitle = chat.turn.approvals?.some((approval) => approval.status === 'pending')
      ? h('span', { class: 'chat-sub amber' }, 'Needs your approval')
      : h('span', { class: 'chat-sub blue' }, 'Replying…');
  }
  els.chatTitle.replaceChildren(
    mascot(avatarType(chat.botId), 'sm'),
    h('div', { class: 'chat-title-text' },
      h('span', { class: 'chat-name' }, chat.thread?.title || bot?.name || 'New chat'),
      subtitle));
  els.textarea.placeholder = `Message ${bot?.name || 'Open Dots'}`;
}

const messageNodes = new Map(); // key -> { el, sig }

function messageItem(message) {
  const key = message.client_id || message.id;
  const time = clock(message.created_at);
  if (message.sender === 'user') {
    return {
      key,
      sig: `u|${message.id}|${message.pending ? 1 : 0}|${time}`,
      build: () => h('div', { class: `msg msg-user${message.pending ? ' pending' : ''}` },
        h('div', { class: 'bubble bubble-user' },
          message.image_url ? h('img', { class: 'bubble-image', src: message.image_url, alt: 'Attached image' }) : null,
          message.text ? h('span', { class: 'bubble-text' }, message.text) : null,
          time ? h('span', { class: 'bubble-time' }, time) : null)),
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

function approvalItem(approval) {
  const busy = state.approvalsBusy.has(approval.requestId);
  const decided = { allow: 'Approved', deny: 'Denied', expired: 'Expired' }[approval.status];
  return {
    key: `approval-${approval.requestId}`,
    sig: `${approval.status}|${busy}`,
    build: () => h('div', { class: 'approval' },
      h('div', { class: 'approval-head' },
        h('span', { class: 'approval-kicker' }, icon('shield', 'icon icon-sm'), 'Permission Broker Request'),
        h('span', { class: 'approval-tool' }, approval.tool || 'action')),
      h('div', { class: 'approval-body' },
        h('span', { class: 'approval-icon' }, icon('terminal', 'icon icon-sm')),
        h('div', null,
          h('p', { class: 'approval-summary' }, approval.summary || 'An action needs your approval.'),
          h('p', { class: 'approval-note' }, `The assistant wants to run this on your ${state.computerKind}.`))),
      decided
        ? h('div', { class: 'approval-foot' },
          h('span', null, 'Status:'),
          h('span', { class: `approval-status ${approval.status}` }, icon(approval.status === 'allow' ? 'check' : 'x', 'icon icon-xs'), decided))
        : h('div', { class: 'approval-actions' },
          h('button', { class: 'btn-deny', type: 'button', disabled: busy, onclick: () => respond(approval.requestId, 'deny') }, icon('x', 'icon icon-sm'), 'Deny'),
          h('button', { class: 'btn-allow', type: 'button', disabled: busy, onclick: () => respond(approval.requestId, 'allow') }, icon('check', 'icon icon-sm'), 'Allow Execution'))),
  };
}

function toolItem(event, index) {
  const status = event.type.replace('tool.', '');
  return {
    key: `tool-${index}-${event.type}-${event.requestId || ''}`,
    sig: status,
    build: () => h('div', { class: 'tool' },
      h('div', { class: 'tool-head' },
        h('span', { class: 'tool-name' }, event.tool || 'workspace'),
        h('span', { class: `tool-status ${status}` }, status)),
      event.error ? h('p', { class: 'tool-error' }, event.error) : null,
      event.result ? h('pre', { class: 'tool-result' }, JSON.stringify(event.result, null, 2)) : null),
  };
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

  const turn = chat.turn;
  const turnItems = turn ? [...(turn.approvals || []).map(approvalItem), ...(turn.tools || []).map(toolItem)] : [];
  let turnPlaced = false;

  if (!chat.messages.length && !turn) {
    const greeting = { id: 'intro', sender: 'bot', text: `Hello! I am **${bot?.name || 'Open Dots Assistant'}**. Ask me anything, or give me a task to work on!` };
    items.push(messageItem(greeting));
  }

  let lastOrigin = null;
  for (const message of chat.messages) {
    if (message.sender === 'user' && message.origin) {
      if (lastOrigin && message.origin !== lastOrigin) {
        const text = `Continued on ${message.origin} · ${clock(message.created_at)}`;
        items.push({ key: `handoff-${message.id}`, sig: text, build: () => h('div', { class: 'handoff' }, h('span', null, text)) });
      }
      lastOrigin = message.origin;
    }
    if (turn && message.id === turn.botMsgId) {
      items.push(...turnItems);
      turnPlaced = true;
    }
    items.push(messageItem(message));
  }

  if (turn && !turnPlaced) {
    items.push(...turnItems);
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
  const ready = (text.trim() || image) && !image?.uploading && !image?.error;
  els.send.disabled = !ready || state.sending || turnRunning();
  els.composer.classList.toggle('multiline', els.textarea.offsetHeight > 30);

  if (!image) {
    els.imageChip.classList.add('hidden');
    els.imageChip.replaceChildren();
    return;
  }
  const note = image.uploading ? 'Preparing image…' : image.error ? image.error : 'Image ready';
  els.imageChip.classList.remove('hidden');
  els.imageChip.replaceChildren(
    h('img', { src: image.previewUrl, alt: 'Selected image' }),
    h('div', { class: 'chip-text' }, h('span', { class: 'chip-name' }, image.name), h('span', { class: image.error ? 'chip-note error' : 'chip-note' }, note)),
    h('button', { class: 'chip-remove', type: 'button', 'aria-label': 'Remove image', onclick: removeImage }, icon('x', 'icon icon-sm')));
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
      (blob) => (blob ? resolve(blob) : reject(new Error('Could not prepare the image.'))),
      'image/jpeg', 0.85,
    ));
  } finally {
    URL.revokeObjectURL(url);
  }
}

async function pickImage() {
  const file = els.file.files?.[0];
  els.file.value = '';
  if (!file) return;
  if (!file.type.startsWith('image/')) {
    toast('Only images can be attached.');
    return;
  }
  removeImage();
  const image = { name: file.name || 'Photo', previewUrl: URL.createObjectURL(file), uploading: true, url: null, error: null };
  state.composer.image = image;
  renderComposer();
  image.done = (async () => {
    try {
      const blob = await downscale(file).catch(() => file);
      const form = new FormData();
      const type = blob.type || file.type;
      form.append('file', blob, `photo.${type === 'image/png' ? 'png' : type === 'image/webp' ? 'webp' : 'jpg'}`);
      image.url = (await api('/upload', { method: 'POST', form })).url;
    } catch (error) {
      image.error = error.message;
    } finally {
      image.uploading = false;
      if (state.composer.image === image) renderComposer();
    }
  })();
}

async function send() {
  const chat = state.chat;
  const text = els.textarea.value;
  const image = state.composer.image;
  if ((!text.trim() && !image) || state.sending || turnRunning() || image?.uploading || image?.error) return;

  const clientId = `c-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
  const optimistic = {
    id: clientId, client_id: clientId, sender: 'user', text, image_url: image?.previewUrl || null,
    created_at: new Date().toISOString(), origin: state.device?.name || 'iPhone', pending: true,
  };
  state.sending = true;
  state.drafts.delete(draftKey());
  state.composer = { text: '', image: null };
  els.textarea.value = '';
  autosize();
  chat.messages.push(optimistic);
  renderComposer();
  renderMessages();
  stickToBottom(true);

  try {
    if (!chat.threadId) {
      const thread = await api('/threads', { method: 'POST', body: { bot_id: chat.botId } });
      chat.threadId = thread.id;
      chat.thread = thread;
      upsertThread(thread);
    }
    const result = await api(`/threads/${encodeURIComponent(chat.threadId)}/messages`, {
      method: 'POST',
      body: { text, image_url: image?.url || null, client_id: clientId },
    });
    if (state.chat !== chat) return;
    upsertMessage(result.message);
    if (!chat.turn || chat.turn.botMsgId !== result.turn.botMsgId) chat.turn = result.turn;
    schedule(renderChatHeader, renderMessages);
  } catch (error) {
    chat.messages = chat.messages.filter((message) => message.client_id !== clientId);
    if (state.chat === chat) {
      els.textarea.value = text;
      state.composer.text = text;
      autosize();
      schedule(renderMessages);
    }
    if (error.status !== 401) toast(error.status === 409 ? 'Wait for the reply to finish.' : error.message);
  } finally {
    state.sending = false;
    if (image) URL.revokeObjectURL(image.previewUrl);
    renderComposer();
  }
}

async function respond(requestId, action) {
  state.approvalsBusy.add(requestId);
  schedule(renderMessages);
  try {
    await api('/approvals/respond', { method: 'POST', body: { request_id: requestId, action } });
  } catch (error) {
    if (error.status === 404) toast('This request was already answered or has expired.');
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
        h('div', { class: 'row-sub' }, bot.role || bot.description || 'Assistant'))))
    : [h('p', { class: 'muted sheet-note' }, `Assistants you create on your ${state.computerKind} show up here.`)]);
  const list = h('div', { class: 'sheet-list' }, ...rows());
  openSheet(
    h('div', { class: 'sheet-head' },
      h('div', null, h('h2', null, 'New chat'), h('p', { class: 'muted' }, 'Choose an assistant')),
      h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Close', onclick: closeSheet }, icon('x'))),
    list);
  try {
    state.bots = await api('/bots');
    list.replaceChildren(...rows());
  } catch { /* the cached roster is shown */ }
}

function openSettings() {
  const linked = state.device?.created_at ? parseTime(state.device.created_at) : null;
  const connection = { live: 'Connected', connecting: 'Connecting…', offline: 'Unavailable' }[state.connection];
  openSheet(
    h('div', { class: 'sheet-head' },
      h('div', { class: 'sheet-computer' },
        h('span', { class: 'computer-icon' }, icon('monitor')),
        h('div', null, h('h2', null, state.computer), h('p', { class: 'muted' }, `${connection} · ${location.host}`))),
      h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Close', onclick: closeSheet }, icon('x'))),
    h('p', { class: 'sheet-copy' },
      `Your conversations are stored on ${state.computer}, and this iPhone connects to it directly — no cloud relay in between. When your ${state.computerKind} sleeps or leaves the network, Open Dots waits for it.`),
    linked ? h('p', { class: 'muted sheet-note' }, `Linked ${linked.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}`) : null,
    state.device
      ? h('button', { class: 'btn-danger', type: 'button', onclick: unlinkThisPhone }, 'Unlink this iPhone')
      : null);
}

async function unlinkThisPhone() {
  if (!window.confirm(`Unlink this iPhone from ${state.computer}? You can link it again with a new code.`)) return;
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

// ----------------------------------------------------------- live events

let source = null;
let offlineTimer = 0;
let retryTimer = 0;
let retryDelay = 1000;
let hiddenAt = 0;

function setConnection(value) {
  if (state.connection === value) return;
  state.connection = value;
  schedule(renderList);
}

function markTrouble() {
  if (state.connection === 'live') setConnection('connecting');
  if (!offlineTimer) offlineTimer = setTimeout(() => { offlineTimer = 0; setConnection('offline'); }, 4000);
}

function connect() {
  clearTimeout(retryTimer);
  source?.close();
  if (state.connection === 'live') setConnection('connecting');
  source = new EventSource('/api/v1/events');
  source.onmessage = (message) => {
    let event;
    try { event = JSON.parse(message.data); } catch { return; }
    handleEvent(event);
  };
  source.onerror = async () => {
    markTrouble();
    if (source?.readyState !== EventSource.CLOSED) return; // the browser retries by itself
    source = null;
    // A refused stream is a network problem or a revoked link; tell them apart.
    try {
      await api('/devices/current');
    } catch (error) {
      if (error.status === 401) return;
    }
    retryTimer = setTimeout(connect, retryDelay);
    retryDelay = Math.min(retryDelay * 2, 15000);
  };
}

document.addEventListener('visibilitychange', () => {
  if (document.hidden) {
    hiddenAt = Date.now();
    return;
  }
  // iOS drops connections in the background; reopen and reload the state.
  if (state.phase === 'app' && (!source || source.readyState !== EventSource.OPEN || Date.now() - hiddenAt > 3000)) connect();
});
window.addEventListener('online', () => { if (state.phase === 'app') connect(); });
window.addEventListener('pageshow', (event) => { if (event.persisted && state.phase === 'app') connect(); });

async function refreshAll() {
  try {
    const [threads, bots] = await Promise.all([api('/threads'), api('/bots')]);
    state.threads = threads;
    state.bots = bots;
    sortThreads();
    saveCache();
    schedule(renderList);
    if (state.chat?.threadId) await loadChat(state.chat.threadId);
    else if (state.chat) schedule(renderChatHeader, renderMessages);
  } catch { /* the connection status already says why */ }
}

function handleEvent(event) {
  const chat = state.chat;
  const inChat = chat?.threadId && event.threadId === chat.threadId;
  const turn = inChat ? chat.turn : null;

  switch (event.type) {
    case 'hello':
      clearTimeout(offlineTimer);
      offlineTimer = 0;
      retryDelay = 1000;
      if (event.computer) state.computer = event.computer;
      setConnection('live');
      refreshAll();
      return;
    case 'resync':
      refreshAll();
      return;
    case 'thread.created':
    case 'thread.updated':
      upsertThread(event.thread);
      return;
    case 'thread.deleted':
      state.threads = state.threads.filter((thread) => thread.id !== event.threadId);
      schedule(renderList);
      if (inChat) {
        history.back();
        toast('That conversation was deleted.');
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
      schedule(renderChatHeader, renderMessages, renderComposer);
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
      schedule(renderChatHeader, renderMessages, renderComposer);
      break;
    default:
      if (event.type.startsWith('tool.') && turn) {
        const { threadId, ...tool } = event;
        turn.tools = [...turn.tools, tool].slice(-5);
        schedule(renderMessages);
      }
  }
}

// -------------------------------------------------------------------- boot

async function boot() {
  // A cached copy lets the app open while the computer is away (HTTPS only).
  if ('serviceWorker' in navigator && window.isSecureContext) {
    navigator.serviceWorker.register('/m/sw.js', { scope: '/m/' }).catch(() => {});
  }
  syncViewport();
  window.visualViewport?.addEventListener('resize', syncViewport);
  window.visualViewport?.addEventListener('scroll', syncViewport);
  window.addEventListener('resize', syncViewport);

  const health = await fetch('/api/v1/health', { cache: 'no-store' }).then((r) => r.json()).catch(() => null);
  if (health?.computer_kind) state.computerKind = health.computer_kind;
  if (!cache.computer) state.computer = `your ${state.computerKind}`;

  const code = normalizeCode(new URLSearchParams(location.search).get('pair'));
  try {
    const current = await api('/devices/current');
    state.device = current.device;
    state.computer = current.computer_name || state.computer;
    if (code) history.replaceState(null, '', '/m/');
    startApp();
    return;
  } catch (error) {
    if (error.status === 0 && cache.computer) {
      // Linked before, computer unreachable now: show what we have and keep trying.
      state.connection = 'offline';
      startApp();
      return;
    }
    if (error.status === 0) {
      renderPair({ mode: 'enter', code: code || '', error: `Can't reach your ${state.computerKind}. Make sure it's awake and on the same Wi-Fi.` });
      return;
    }
  }

  if (!code) renderPair({ mode: 'enter' });
  else if (isIOS() && !isStandalone()) renderPair({ mode: 'install', code });
  else link(code);
}

boot();
