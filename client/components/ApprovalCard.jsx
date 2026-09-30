'use client';

import React, { useState } from 'react';
import { FiShield, FiTerminal, FiCheck, FiX } from 'react-icons/fi';
import { TOOL_STATUS, toolLabel } from '../lib/liveChat';

const HEADINGS = {
  pending: 'Approval needed',
  allow: 'Approved',
  deny: 'Denied',
  expired: 'Not answered in time',
};

const HEADING_COLORS = {
  pending: 'text-amber-400',
  allow: 'text-emerald-400',
  deny: 'text-rose-400',
  expired: 'text-zinc-400',
};

const STATUS_COLORS = {
  completed: 'text-emerald-400',
  failed: 'text-rose-400',
  started: 'text-amber-400',
};

export function ResultDetails({ result }) {
  if (!result) return null;
  return (
    <details className="mt-1 text-slate-400">
      <summary className="cursor-pointer text-[10px]">Details</summary>
      <pre className="mt-1 max-h-28 overflow-auto whitespace-pre-wrap font-mono text-[10px] text-slate-400">
        {JSON.stringify(result, null, 2)}
      </pre>
    </details>
  );
}

export function ActionStatus({ event }) {
  const status = event.type.replace('tool.', '');
  return <span className={STATUS_COLORS[status] || 'text-zinc-400'}>{TOOL_STATUS[status] || status}</span>;
}

export default function ApprovalCard({ approval, result, onRespond }) {
  const [localStatus, setLocalStatus] = useState('pending');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState('');
  // The request may be answered on another device; the server's status wins.
  const status = approval.status && approval.status !== 'pending' ? approval.status : localStatus;

  const handleAction = async (action) => {
    setIsSubmitting(true);
    setError('');
    try {
      if (onRespond) {
        await onRespond(approval.requestId, action);
      }
      setLocalStatus(action);
    } catch (err) {
      setError(err?.message || "Couldn't send your answer.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className={`my-3 p-4 rounded-2xl border bg-slate-900/80 shadow-xl max-w-xl ${status === 'pending' ? 'border-amber-500/30' : 'border-slate-800'}`}>
      <div className="flex items-center justify-between border-b border-slate-800/80 pb-2 mb-3">
        <div className={`flex items-center gap-2 ${HEADING_COLORS[status] || 'text-zinc-400'}`}>
          <FiShield className={`text-lg ${status === 'pending' ? 'animate-pulse' : ''}`} />
          <span className="text-xs font-bold uppercase tracking-wider">{HEADINGS[status] || 'Approval'}</span>
        </div>
        <span className="text-[10px] bg-slate-800/60 text-slate-300 px-2 py-0.5 rounded border border-slate-700">
          {toolLabel(approval.tool)}
        </span>
      </div>

      <div className="flex items-center gap-3 my-2">
        <div className="w-8 h-8 rounded-lg bg-slate-800 flex items-center justify-center text-amber-400 border border-slate-700 flex-shrink-0">
          <FiTerminal className="text-base" />
        </div>
        <p className="text-xs font-medium text-slate-200">{approval.summary}</p>
      </div>

      {status === 'pending' ? (
        <div className="flex items-center justify-end gap-2 mt-4 pt-2 border-t border-slate-800/60">
          {error && <span className="mr-auto text-[10px] text-rose-400">{error}</span>}
          <button
            disabled={isSubmitting}
            onClick={() => handleAction('deny')}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-slate-800 hover:bg-rose-500/20 text-rose-400 hover:text-rose-300 border border-slate-700 hover:border-rose-500/40 text-xs font-semibold transition disabled:opacity-50"
          >
            <FiX className="text-sm" />
            <span>Deny</span>
          </button>
          <button
            disabled={isSubmitting}
            onClick={() => handleAction('allow')}
            className="flex items-center gap-1.5 px-4 py-1.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold shadow-lg shadow-emerald-600/30 transition disabled:opacity-50"
          >
            <FiCheck className="text-sm" />
            <span>Allow</span>
          </button>
        </div>
      ) : status === 'allow' && result ? (
        <div className="mt-3 pt-2 border-t border-slate-800/60 text-[11px]">
          <ActionStatus event={result} />
          {result.error && <p className="mt-1 text-rose-300">{result.error}</p>}
          <ResultDetails result={result.result} />
        </div>
      ) : null}
    </div>
  );
}
