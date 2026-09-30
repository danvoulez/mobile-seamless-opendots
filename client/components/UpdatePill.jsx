'use client';

import React, { useEffect, useState } from 'react';
import { FiArrowUp, FiCheck, FiClock, FiAlertTriangle } from 'react-icons/fi';

const RECENT_MS = 3 * 60 * 1000;

function recent(at) {
  const time = at ? Date.parse(at) : NaN;
  return Number.isFinite(time) && Date.now() - time < RECENT_MS;
}

export function changeSummary(available) {
  if (!available) return '';
  const count = available.count || 1;
  const lines = (available.changes || []).slice(0, 5).map((change) => `• ${change.subject}`);
  return [`${count} ${count === 1 ? 'change' : 'changes'}`, ...lines].join('\n');
}

// One small pill next to "new chat": Update (one click installs it),
// Updating…, or a short note after an update finished or went back.
export default function UpdatePill({ update, onInstall, onOpenSettings }) {
  const [, tick] = useState(0);
  const last = update?.last;
  const showUpdated = last?.state === 'done' && last.to === update?.current?.commit && recent(last.at);
  const showFailed = ['rolled-back', 'failed'].includes(last?.state) && last.to && recent(last.at);

  // Let the "Updated" note fade away on its own.
  useEffect(() => {
    if (!showUpdated && !showFailed) return undefined;
    const timer = setTimeout(() => tick((n) => n + 1), RECENT_MS);
    return () => clearTimeout(timer);
  }, [showUpdated, showFailed]);

  if (!update) return null;
  const base = 'flex items-center gap-1.5 h-6 px-2.5 rounded-full text-[11px] font-semibold transition animate-fade-in';

  if (update.state === 'updating') {
    return (
      <span role="status" className={`${base} bg-white/[0.055] text-zinc-300`}>
        <span className="w-2.5 h-2.5 rounded-full border-2 border-blue-400/25 border-t-blue-400 animate-spin" />
        Updating…
      </span>
    );
  }
  if (update.state === 'waiting') {
    return (
      <span role="status" title="Open Dots updates as soon as the current reply finishes." className={`${base} bg-white/[0.055] text-zinc-400`}>
        <FiClock className="w-3 h-3" /> After this reply
      </span>
    );
  }
  if (update.available) {
    const ready = update.can_update;
    return (
      <button
        type="button"
        onClick={ready ? onInstall : onOpenSettings}
        title={ready ? `Install the new version now\n${changeSummary(update.available)}` : update.reason}
        className={`${base} bg-blue-500/10 text-blue-300 ring-1 ring-blue-400/25 hover:bg-blue-500/20`}
      >
        <FiArrowUp className="w-3 h-3" strokeWidth={2.5} /> Update
      </button>
    );
  }
  if (showFailed) {
    return (
      <button type="button" onClick={onOpenSettings} title={last.message} className={`${base} bg-amber-500/10 text-amber-300 hover:bg-amber-500/15`}>
        <FiAlertTriangle className="w-3 h-3" /> Update didn&apos;t work
      </button>
    );
  }
  if (showUpdated) {
    return (
      <span role="status" title={update.current?.subject} className={`${base} bg-emerald-400/10 text-emerald-300`}>
        <FiCheck className="w-3 h-3" strokeWidth={2.5} /> Updated
      </span>
    );
  }
  return null;
}
