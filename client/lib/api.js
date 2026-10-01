// The Open Dots server serves this page, so the API is on the same address.
// `npm run dev` serves the page from another port and sets this (package.json).
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || '/api/v1';

let sessionPromise = null;

export class AuthenticationError extends Error {}

function sessionExpired() {
  sessionPromise = null;
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new Event('open-dots:authentication-required'));
  }
}

export async function ensureSession() {
  if (typeof window === 'undefined') return null;
  if (!sessionPromise) {
    sessionPromise = fetch(`${API_BASE_URL}/auth/session`, {
      credentials: 'include',
    })
      .then((res) => {
        if (res.status === 401) throw new AuthenticationError('Sign in to Open Dots.');
        if (!res.ok) throw new Error('Could not reach the authentication service.');
        return res.json();
      })
      .catch((err) => {
        sessionPromise = null;
        throw err;
      });
  }
  return sessionPromise;
}

async function apiFetch(url, options = {}) {
  try {
    await ensureSession();
  } catch (error) {
    if (error instanceof AuthenticationError) sessionExpired();
    throw error;
  }
  const response = await fetch(url, {
    ...options,
    credentials: 'include',
  });
  if (response.status === 401) {
    sessionExpired();
    throw new AuthenticationError('Your session expired. Sign in again.');
  }
  return response;
}

export async function login(token) {
  const response = await fetch(`${API_BASE_URL}/auth/login`, {
    method: 'POST', credentials: 'include',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token }),
  });
  if (response.status === 401) throw new AuthenticationError('The owner token is incorrect.');
  if (!response.ok) throw new Error('Sign-in failed. Check the API connection and allowed origins.');
  const session = await response.json();
  sessionPromise = Promise.resolve(session);
  return session;
}

// A one-time link from the installer or `start-mac.sh --sign-in`.
export async function signInWithCode(code) {
  const response = await fetch(`${API_BASE_URL}/auth/signin`, {
    method: 'POST', credentials: 'include',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code }),
  });
  if (response.status === 401) throw new AuthenticationError('This sign-in link has expired or was already used.');
  if (!response.ok) throw new Error('Sign-in failed. Check the API connection.');
  const session = await response.json();
  sessionPromise = Promise.resolve(session);
  return session;
}

export async function logout() {
  const response = await fetch(`${API_BASE_URL}/auth/logout`, { method: 'POST', credentials: 'include' });
  if (!response.ok) throw new Error('Could not sign out. Reconnect to the API and retry.');
  sessionExpired();
}

export async function fetchBots() {
  try {
    const res = await apiFetch(`${API_BASE_URL}/bots`);
    if (!res.ok) return [];
    return await res.json();
  } catch (err) {
    console.warn('Backend server offline or unreachable:', err);
    return [];
  }
}

export async function createBot(botData) {
  const res = await apiFetch(`${API_BASE_URL}/bots`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(botData),
  });
  if (!res.ok) throw new Error('Failed to create bot');
  return res.json();
}

export async function updateBot(botId, updates) {
  const res = await apiFetch(`${API_BASE_URL}/bots/${botId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(updates),
  });
  if (!res.ok) throw new Error('Failed to update bot');
  return res.json();
}

export async function deleteBot(botId) {
  const res = await apiFetch(`${API_BASE_URL}/bots/${botId}`, { method: 'DELETE' });
  if (!res.ok) throw new Error('Failed to delete bot');
  return res.json();
}

export async function fetchModels() {
  try {
    const res = await apiFetch(`${API_BASE_URL}/models`);
    if (!res.ok) return [];
    return await res.json();
  } catch (err) {
    console.warn('Models catalog API offline:', err);
    return [];
  }
}

export async function fetchChatHistory(threadId) {
  try {
    const res = await apiFetch(`${API_BASE_URL}/chat/history/${threadId}`);
    if (!res.ok) return [];
    return await res.json();
  } catch (err) {
    console.warn('Chat history API offline:', err);
    return [];
  }
}

export async function sendMessage(threadId, botId, text, model = 'gpt-5-mini', imageUrl = null) {
  try {
    const res = await apiFetch(`${API_BASE_URL}/chat/send`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        thread_id: threadId,
        bot_id: botId,
        user_text: text,
        model,
        image_url: imageUrl,
      }),
    });
    if (!res.ok) throw new Error('Failed to send message');
    return await res.json();
  } catch (err) {
    console.warn('Send message API call error:', err);
    return { status: 'error', detail: err.message };
  }
}

// Photos go to the model with every reply that still needs them; models see
// about 1600 px at most anyway, so a bigger one only costs time. Same rule as
// the iPhone app (mobile/app.js, downscale).
const MAX_IMAGE_SIDE = 1600;

async function downscaleImage(file) {
  const url = URL.createObjectURL(file);
  try {
    const img = await new Promise((resolve, reject) => {
      const image = new Image();
      image.onload = () => resolve(image);
      image.onerror = reject;
      image.src = url;
    });
    const scale = Math.min(1, MAX_IMAGE_SIDE / Math.max(img.naturalWidth, img.naturalHeight));
    if (scale === 1 && file.size < 1_500_000 && /^image\/(jpeg|png|webp)$/.test(file.type)) return file;
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(img.naturalWidth * scale);
    canvas.height = Math.round(img.naturalHeight * scale);
    canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise((resolve, reject) => canvas.toBlob(
      (result) => (result ? resolve(result) : reject(new Error('Could not prepare the image.'))),
      'image/jpeg', 0.85,
    ));
    return new File([blob], `${(file.name || 'image').replace(/\.[^.]+$/, '')}.jpg`, { type: 'image/jpeg' });
  } catch {
    return file; // a format this browser can't draw: send it as it is
  } finally {
    URL.revokeObjectURL(url);
  }
}

export async function uploadImage(file) {
  const formData = new FormData();
  formData.append('file', await downscaleImage(file));
  const res = await apiFetch(`${API_BASE_URL}/upload`, {
    method: 'POST',
    body: formData,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Failed to upload image' }));
    throw new Error(err.detail || 'Failed to upload image');
  }
  return res.json();
}

export async function fetchConnectorCatalog() {
  try {
    const res = await apiFetch(`${API_BASE_URL}/connectors/catalog`);
    if (!res.ok) return { cards: [], source: 'curated', configured: false };
    return await res.json();
  } catch (err) {
    console.warn('Connector catalog offline:', err);
    return { cards: [], source: 'curated', configured: false };
  }
}

export async function fetchConnectionStatus(slugs = []) {
  if (!slugs.length) return { services: {} };
  try {
    const res = await apiFetch(`${API_BASE_URL}/connectors?services=${encodeURIComponent(slugs.join(','))}`);
    if (!res.ok) return { services: {} };
    return await res.json();
  } catch (err) {
    console.warn('Connection status offline:', err);
    return { services: {} };
  }
}

export async function authorizeConnector(slug) {
  const res = await apiFetch(`${API_BASE_URL}/connectors/${slug}/authorize`, { method: 'POST' });
  if (!res.ok) throw new Error(`Failed to authorize ${slug}`);
  return res.json();
}

export async function disconnectConnector(slug) {
  const res = await apiFetch(`${API_BASE_URL}/connectors/${slug}`, { method: 'DELETE' });
  if (!res.ok) throw new Error(`Failed to disconnect ${slug}`);
  return res.json();
}

// What the model calls of the last `days` days used and cost (see routers/audit.py).
export async function fetchModelUsage(days = 30) {
  const res = await apiFetch(`${API_BASE_URL}/audit/usage?days=${encodeURIComponent(days)}`);
  if (!res.ok) throw new Error('Could not load model usage.');
  return res.json();
}

export async function fetchAuditEvents(limit = 100) {
  try {
    const res = await apiFetch(`${API_BASE_URL}/audit?limit=${encodeURIComponent(limit)}`);
    if (!res.ok) return [];
    return await res.json();
  } catch (err) {
    console.warn('Audit API offline:', err);
    return [];
  }
}

export function subscribeToChatStream(threadId, model, onEvent, onError) {
  const url = `${API_BASE_URL}/chat/stream/${threadId}?model=${encodeURIComponent(model)}`;
  let eventSource = null;
  let cancelled = false;

  ensureSession()
    .then(() => {
      if (cancelled) return;
      eventSource = new EventSource(url, { withCredentials: true });

      eventSource.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data);
          if (onEvent) onEvent(data);
        } catch (err) {
          console.warn('Failed to parse SSE payload:', err);
        }
      };

      eventSource.onerror = (err) => {
        // Gracefully close stream when completed or disconnected
        if (eventSource) {
          eventSource.close();
        }
        if (onError && typeof onError === 'function') {
          onError(err);
        }
        sessionPromise = null;
        ensureSession().catch((error) => {
          if (error instanceof AuthenticationError) sessionExpired();
        });
      };
    })
    .catch((err) => {
      console.warn('Authentication or EventSource initialization error:', err);
      if (onError && typeof onError === 'function') {
        onError(err);
      }
    });

  return () => {
    cancelled = true;
    if (eventSource) {
      eventSource.close();
    }
  };
}

export async function respondApproval(requestId, action) {
  const res = await apiFetch(`${API_BASE_URL}/approvals/respond`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ request_id: requestId, action }),
  });
  if (!res.ok) throw new Error('Failed to respond approval');
  return res.json();
}

// ----- updates for this Mac's copy of Open Dots ---------------------------------

async function updateRequest(path, options = {}) {
  const res = await apiFetch(`${API_BASE_URL}/system/update${path}`, options);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || "Couldn't reach the update service.");
  return body;
}

export function fetchUpdateStatus() {
  return updateRequest('');
}

export function checkForUpdate() {
  return updateRequest('/check', { method: 'POST' });
}

export function installUpdate() {
  return updateRequest('', { method: 'POST' });
}

export function setAutoUpdate(auto) {
  return updateRequest('', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ auto }),
  });
}

export async function fetchSettings() {
  try {
    const res = await apiFetch(`${API_BASE_URL}/settings`);
    if (!res.ok) return null;
    return await res.json();
  } catch (err) {
    console.warn('Fetch settings API offline:', err);
    return null;
  }
}

export async function saveSettings(settingsData) {
  const res = await apiFetch(`${API_BASE_URL}/settings`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(settingsData),
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({}));
    const detail = Array.isArray(error.detail)
      ? error.detail.map((item) => item.msg).join(' ')
      : error.detail;
    throw new Error(detail || 'Failed to save settings');
  }
  return res.json();
}

export async function fetchComputerStatus(botId) {
  const res = await apiFetch(`${API_BASE_URL}/computers/${encodeURIComponent(botId)}`);
  if (!res.ok) throw new Error('Failed to load computer status');
  return res.json();
}

export async function fetchComputerHealth(botId) {
  const res = await apiFetch(`${API_BASE_URL}/computers/${encodeURIComponent(botId)}/health`);
  if (!res.ok) throw new Error('Failed to load computer health');
  return res.json();
}

export async function fetchComputerScreenshot(botId) {
  const res = await apiFetch(`${API_BASE_URL}/computers/${encodeURIComponent(botId)}/screenshot`);
  if (!res.ok) throw new Error('Failed to load computer screen state');
  return res.json();
}

async function runComputerLifecycleAction(botId, action) {
  const res = await apiFetch(`${API_BASE_URL}/computers/${encodeURIComponent(botId)}/${action}`, {
    method: 'POST',
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({}));
    throw new Error(error.detail || `Computer ${action} failed`);
  }
  return res.json();
}

export function createComputer(botId) {
  return runComputerLifecycleAction(botId, 'create');
}

export function startComputer(botId) {
  return runComputerLifecycleAction(botId, 'start');
}

export function pauseComputer(botId) {
  return runComputerLifecycleAction(botId, 'pause');
}

export function stopComputer(botId) {
  return runComputerLifecycleAction(botId, 'stop');
}

export function resetComputer(botId) {
  return runComputerLifecycleAction(botId, 'reset');
}

export async function runComputerAction(botId, action, argumentsData = {}) {
  const res = await apiFetch(`${API_BASE_URL}/computers/${encodeURIComponent(botId)}/actions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action, arguments: argumentsData }),
  });
  const payload = await res.json().catch(() => ({}));
  if (!res.ok && res.status !== 202) {
    throw new Error(payload.detail || 'Computer action failed');
  }
  return payload;
}

export async function executeComputerAction(botId, requestId) {
  const res = await apiFetch(
    `${API_BASE_URL}/computers/${encodeURIComponent(botId)}/actions/${encodeURIComponent(requestId)}/execute`,
    { method: 'POST' },
  );
  const payload = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(payload.detail || 'Computer action execution failed');
  return payload;
}

// ----- Conversations shared with linked devices ------------------------------

async function readError(res, fallback) {
  const payload = await res.json().catch(() => ({}));
  const detail = Array.isArray(payload.detail)
    ? payload.detail.map((item) => item.msg).join(' ')
    : payload.detail;
  const error = new Error(detail || fallback);
  error.status = res.status;
  return error;
}

export async function fetchThreads() {
  try {
    const res = await apiFetch(`${API_BASE_URL}/threads`);
    if (!res.ok) return [];
    return await res.json();
  } catch (err) {
    console.warn('Conversations API offline:', err);
    return [];
  }
}

export async function fetchThread(threadId) {
  const res = await apiFetch(`${API_BASE_URL}/threads/${encodeURIComponent(threadId)}`);
  if (!res.ok) throw await readError(res, 'Failed to load conversation');
  return res.json();
}

export async function createThread(botId) {
  const res = await apiFetch(`${API_BASE_URL}/threads`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ bot_id: botId }),
  });
  if (!res.ok) throw await readError(res, 'Failed to start a conversation');
  return res.json();
}

export async function deleteThread(threadId) {
  const res = await apiFetch(`${API_BASE_URL}/threads/${encodeURIComponent(threadId)}`, { method: 'DELETE' });
  if (!res.ok) throw await readError(res, 'Failed to delete conversation');
  return res.json();
}

export async function postThreadMessage(threadId, { text, imageUrl = null, model = null, clientId = null }) {
  const res = await apiFetch(`${API_BASE_URL}/threads/${encodeURIComponent(threadId)}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, image_url: imageUrl, model, client_id: clientId }),
  });
  if (!res.ok) throw await readError(res, 'Failed to send message');
  return res.json();
}

// One live stream for the whole workspace: messages, reply deltas, approvals
// and conversation list changes from this computer and linked devices.
// Staying connected is the normal state: it reconnects on its own, notices a
// stream that died silently, and only reports trouble that lasts.
export function subscribeToEvents(onEvent, onStatus) {
  let source = null;
  let retryTimer = null;
  let troubleTimer = null;
  let retryDelay = 1000;
  let lastEventAt = Date.now();
  let closed = false;

  const trouble = () => {
    if (!troubleTimer) troubleTimer = setTimeout(() => onStatus?.('reconnecting'), 3000);
  };

  const retry = () => {
    clearTimeout(retryTimer);
    retryTimer = setTimeout(connect, retryDelay);
    retryDelay = Math.min(retryDelay * 2, 5000);
  };

  function connect() {
    if (closed) return;
    source?.close();
    source = null;
    lastEventAt = Date.now();
    ensureSession()
      .then(() => {
        if (closed) return;
        source = new EventSource(`${API_BASE_URL}/events`, { withCredentials: true });
        source.onmessage = (e) => {
          lastEventAt = Date.now();
          try {
            const event = JSON.parse(e.data);
            if (event.type === 'hello') {
              retryDelay = 1000;
              clearTimeout(troubleTimer);
              troubleTimer = null;
              onStatus?.('live');
            }
            if (event.type !== 'heartbeat') onEvent(event);
          } catch (err) {
            console.warn('Failed to parse event payload:', err);
          }
        };
        source.onerror = () => {
          trouble();
          if (source?.readyState !== EventSource.CLOSED) return; // the browser retries
          source = null;
          sessionPromise = null;
          retry();
        };
      })
      .catch((error) => {
        if (error instanceof AuthenticationError) {
          sessionExpired();
          return;
        }
        trouble();
        retry();
      });
  }

  // The server sends a heartbeat every 15 s; silence means the stream died.
  const watchdog = setInterval(() => {
    if (!closed && source && Date.now() - lastEventAt > 40000) connect();
  }, 5000);

  connect();
  return () => {
    closed = true;
    clearTimeout(retryTimer);
    clearTimeout(troubleTimer);
    clearInterval(watchdog);
    source?.close();
  };
}

// ----- Continue on iPhone ----------------------------------------------------

export async function createPairing() {
  const res = await apiFetch(`${API_BASE_URL}/devices/pairing`, { method: 'POST' });
  if (!res.ok) throw await readError(res, 'Could not create a linking code');
  return res.json();
}

export async function fetchDevices() {
  const res = await apiFetch(`${API_BASE_URL}/devices`);
  if (!res.ok) throw await readError(res, 'Could not load linked devices');
  return res.json();
}

export async function unlinkDevice(deviceId) {
  const res = await apiFetch(`${API_BASE_URL}/devices/${encodeURIComponent(deviceId)}`, { method: 'DELETE' });
  if (!res.ok) throw await readError(res, 'Could not unlink the device');
  return res.json();
}
