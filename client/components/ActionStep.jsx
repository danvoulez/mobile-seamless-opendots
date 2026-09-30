'use client';

import React, { useState } from 'react';
import { FiShield, FiCheck, FiX, FiMinus } from 'react-icons/fi';
import { stepKind, stepStatus, toolLabel } from '../lib/liveChat';

const ICONS = { ask: FiShield, done: FiCheck, failed: FiX, skipped: FiMinus };

const ICON_STYLES = {
  ask: 'bg-amber-500/10 text-amber-300 ring-1 ring-amber-500/35',
  working: 'bg-blue-400/10',
  done: 'bg-emerald-400/10 text-emerald-400',
  failed: 'bg-rose-400/10 text-rose-400',
  skipped: 'bg-white/[0.055] text-zinc-400',
};

const STATUS_STYLES = { ask: 'text-amber-300', failed: 'text-rose-400' };

// One thing the assistant does in a reply: a small status circle, a line of
// text, and a thin rail down to the next step, so a busy reply reads as a
// quick run of steps rather than a stack of cards. Matches the iPhone.
export default function ActionStep({ approval, event, preview, last, onRespond }) {
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState('');
  const kind = stepKind(approval, event);
  const label = toolLabel(approval?.tool || event?.tool);
  const title = approval?.summary || preview || label;
  const Icon = ICONS[kind];

  const answer = async (action) => {
    setIsSubmitting(true);
    setError('');
    try {
      await onRespond(approval.requestId, action);
      // Stay disabled until the answer comes back as an event.
    } catch (err) {
      setError(err?.message || "Couldn't send your answer.");
      setIsSubmitting(false);
    }
  };

  return (
    <div className="relative grid grid-cols-[20px_minmax(0,1fr)] gap-2.5 max-w-xl py-1 pl-1 animate-step-in">
      {!last && <span aria-hidden="true" className="absolute left-[13.5px] top-[27px] -bottom-px w-px bg-white/[0.07]" />}
      <span className={`w-5 h-5 rounded-full flex items-center justify-center ${ICON_STYLES[kind]}`}>
        {kind === 'working'
          ? <span className="w-2.5 h-2.5 rounded-full border-2 border-blue-400/25 border-t-blue-400 animate-spin" />
          : <Icon className="w-3 h-3" strokeWidth={2.5} />}
      </span>
      <div className="min-w-0">
        <p className={`text-xs leading-5 break-words ${kind === 'skipped' ? 'text-zinc-400' : 'text-zinc-200'}`}>{title}</p>
        <p className="flex flex-wrap items-baseline gap-x-1.5 text-[11px] text-zinc-500">
          {title !== label && (
            <>
              <span className="font-mono text-[10px]">{label}</span>
              <span aria-hidden="true">·</span>
            </>
          )}
          <span className={STATUS_STYLES[kind] || ''}>{stepStatus(kind, approval)}</span>
        </p>
        {event?.error && <p className="mt-0.5 text-[11px] text-rose-300 break-words">{event.error}</p>}
        {kind === 'ask' && (
          <div className="flex items-center gap-2 mt-2 mb-1">
            <button
              type="button"
              disabled={isSubmitting}
              onClick={() => answer('deny')}
              className="h-7 px-3.5 rounded-full border border-white/[0.07] bg-white/[0.03] hover:bg-white/[0.055] text-zinc-300 text-[11px] font-semibold transition disabled:opacity-50"
            >
              Deny
            </button>
            <button
              type="button"
              disabled={isSubmitting}
              onClick={() => answer('allow')}
              className="h-7 px-3.5 rounded-full bg-emerald-600 hover:bg-emerald-500 text-white text-[11px] font-semibold flex items-center gap-1 transition disabled:opacity-50"
            >
              <FiCheck className="w-3 h-3" strokeWidth={2.5} />
              <span>Allow</span>
            </button>
            {error && <span role="alert" className="text-[11px] text-rose-400">{error}</span>}
          </div>
        )}
        {event?.result && (
          <details className="mt-0.5">
            <summary className="w-fit cursor-pointer text-[11px] text-zinc-500 hover:text-zinc-400">Details</summary>
            <pre className="mt-1.5 mb-0.5 max-h-36 overflow-auto whitespace-pre-wrap rounded-lg border border-white/[0.07] bg-white/[0.03] px-2.5 py-2 font-mono text-[10px] leading-relaxed text-zinc-400 select-text">
              {JSON.stringify(event.result, null, 2)}
            </pre>
          </details>
        )}
      </div>
    </div>
  );
}
