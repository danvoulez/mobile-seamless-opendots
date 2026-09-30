'use client';

import React, { useState } from 'react';

function when(value) {
  const time = value ? Date.parse(value) : NaN;
  if (!Number.isFinite(time)) return '';
  const minutes = Math.round((Date.now() - time) / 60000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes} min ago`;
  return new Date(time).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}

function day(value) {
  const time = value ? Date.parse(value) : NaN;
  return Number.isFinite(time) ? new Date(time).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : '';
}

// Settings → Updates: which version runs, what's new, and whether new
// versions install by themselves.
export default function UpdatesCard({ update, onCheck, onInstall, onSetAuto }) {
  const [busy, setBusy] = useState(''); // which action is running
  const [error, setError] = useState('');

  const run = async (name, action) => {
    setBusy(name);
    setError('');
    try {
      await action();
    } catch (failure) {
      setError(failure.message);
    } finally {
      setBusy('');
    }
  };

  if (!update) return null;
  const { current, available, last } = update;
  const failed = ['rolled-back', 'failed'].includes(last?.state) && last?.to;

  return (
    <section aria-labelledby="updates-title" className="bg-[#18181b] border border-[#27272a] rounded-2xl p-4 space-y-3">
      <div className="flex items-baseline justify-between gap-3">
        <h3 id="updates-title" className="text-sm font-semibold">Updates</h3>
        {current && (
          <span className="text-[11px] text-zinc-500 font-mono" title={current.subject}>
            {current.short} · {day(current.date)}
          </span>
        )}
      </div>

      <label className="flex items-start gap-3 cursor-pointer">
        <input
          type="checkbox"
          checked={Boolean(update.auto)}
          disabled={Boolean(busy)}
          onChange={(event) => run('auto', () => onSetAuto(event.target.checked))}
          className="mt-0.5 accent-blue-500"
        />
        <span>
          <span className="block text-xs text-zinc-200">Install updates automatically</span>
          <span className="block text-[11px] text-zinc-500 mt-0.5">New versions that pass their tests install while no reply is running. Open Dots restarts for a few seconds; your iPhone reconnects by itself.</span>
        </span>
      </label>

      {available ? (
        <div className="space-y-2">
          <p className="text-xs text-zinc-200">
            A new version is ready · {available.count} {available.count === 1 ? 'change' : 'changes'}
          </p>
          <ul className="space-y-1">
            {(available.changes || []).slice(0, 5).map((change) => (
              <li key={change.short} className="text-[11px] text-zinc-400 flex gap-2">
                <span className="font-mono text-zinc-600">{change.short}</span>
                <span className="min-w-0 break-words">{change.subject}</span>
              </li>
            ))}
          </ul>
          {available.failed_before && (
            <p className="text-[11px] text-amber-300">This version didn&apos;t start last time, so it won&apos;t install by itself.</p>
          )}
        </div>
      ) : (
        <p className="text-xs text-zinc-400">
          {update.checked_at ? `Up to date · checked ${when(update.checked_at)}` : 'Not checked yet'}
        </p>
      )}

      {failed && (
        <p className="text-[11px] text-amber-300">{last.message} ({when(last.at)}).</p>
      )}
      {update.check_error && <p className="text-[11px] text-amber-300">{update.check_error}</p>}
      {update.reason && <p className="text-[11px] text-zinc-500">{update.reason}</p>}
      {error && <p role="alert" className="text-[11px] text-rose-400">{error}</p>}

      <div className="flex gap-2">
        {available && update.can_update && (
          <button
            type="button"
            disabled={Boolean(busy) || update.state !== 'idle'}
            onClick={() => run('install', onInstall)}
            className="h-8 px-4 rounded-full bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold transition disabled:opacity-50"
          >
            {update.state === 'updating' ? 'Updating…' : update.state === 'waiting' ? 'After this reply…' : 'Update now'}
          </button>
        )}
        <button
          type="button"
          disabled={Boolean(busy)}
          onClick={() => run('check', onCheck)}
          className="h-8 px-4 rounded-full border border-white/[0.07] bg-white/[0.03] hover:bg-white/[0.055] text-zinc-300 text-xs font-semibold transition disabled:opacity-50"
        >
          {busy === 'check' ? 'Checking…' : 'Check now'}
        </button>
      </div>
    </section>
  );
}
