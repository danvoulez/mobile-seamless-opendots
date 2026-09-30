// Merge live workspace events into client state.
//
// The same conversation can be open on this computer and on a linked phone.
// Both receive the same events; these helpers keep each copy consistent,
// including when a client joins a reply halfway through.

const COMPUTER_ORIGINS = new Set(['Mac', 'Computer']);

export function isDeviceOrigin(origin) {
  return Boolean(origin) && !COMPUTER_ORIGINS.has(origin);
}

function time(value) {
  const parsed = value ? new Date(value).getTime() : 0;
  return Number.isNaN(parsed) ? 0 : parsed;
}

export function upsertThread(threads, summary) {
  const next = threads.filter((thread) => thread.id !== summary.id);
  next.push(summary);
  return next.sort((a, b) => time(b.updated_at) - time(a.updated_at));
}

export function upsertMessage(messages, message) {
  const index = messages.findIndex((item) => item.id === message.id
    || (message.client_id && item.client_id === message.client_id));
  if (index === -1) return [...messages, message];
  const next = [...messages];
  next[index] = message;
  return next;
}

export const emptyChat = { messages: [], turn: null, loading: false, needsReload: false };

export function mergeSnapshot(chat, detail) {
  const confirmed = new Set(detail.messages.map((message) => message.client_id).filter(Boolean));
  const unconfirmed = chat.messages.filter((message) => message.pending && !confirmed.has(message.client_id));
  let turn = detail.turn;
  // Deltas that arrived while the snapshot was loading may be ahead of it.
  if (turn && chat.turn?.botMsgId === turn.botMsgId && chat.turn.text.length > turn.text.length) {
    turn = { ...turn, text: chat.turn.text };
  }
  return { messages: [...detail.messages, ...unconfirmed], turn, loading: false, needsReload: false };
}

// Returns the next chat state; sets needsReload when the snapshot must be refetched.
export function applyChatEvent(chat, event) {
  const turn = chat.turn;
  switch (event.type) {
    case 'message.created':
      return { ...chat, messages: upsertMessage(chat.messages, event.message) };
    case 'turn.started':
      if (turn?.botMsgId === event.botMsgId && turn.status === 'running') return chat;
      return {
        ...chat,
        turn: { turnId: event.turnId, botMsgId: event.botMsgId, model: event.model, status: 'running', text: '', approvals: [], tools: [] },
      };
    case 'content.delta': {
      if (!turn || turn.botMsgId !== event.botMsgId || event.offset > turn.text.length) {
        return { ...chat, needsReload: true };
      }
      if (event.offset + event.delta.length <= turn.text.length) return chat;
      return { ...chat, turn: { ...turn, text: turn.text.slice(0, event.offset) + event.delta } };
    }
    case 'request.opened': {
      if (!turn) return { ...chat, needsReload: true };
      const approval = {
        requestId: event.requestId, tool: event.tool, summary: event.summary, arguments: event.arguments, status: 'pending',
      };
      return {
        ...chat,
        turn: { ...turn, approvals: [...turn.approvals.filter((a) => a.requestId !== event.requestId), approval] },
      };
    }
    case 'request.resolved':
      if (!turn) return chat;
      return {
        ...chat,
        turn: {
          ...turn,
          approvals: turn.approvals.map((a) => (a.requestId === event.requestId ? { ...a, status: event.decision } : a)),
        },
      };
    case 'turn.completed':
      return {
        ...chat,
        messages: event.message ? upsertMessage(chat.messages, event.message) : chat.messages,
        turn: turn ? { ...turn, status: event.ok ? 'completed' : 'failed' } : turn,
      };
    default:
      if (event.type?.startsWith('tool.') && turn) {
        const { threadId, ...tool } = event;
        return { ...chat, turn: { ...turn, tools: [...turn.tools, tool].slice(-5) } };
      }
      return chat;
  }
}
