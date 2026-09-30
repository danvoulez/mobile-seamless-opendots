'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { FiSmartphone, FiX, FiRefreshCw, FiCheck, FiAlertTriangle } from 'react-icons/fi';
import { createPairing, fetchDevices, unlinkDevice } from '../lib/api';

function QrCode({ rows }) {
  const quiet = 4;
  const size = rows.length + quiet * 2;
  const path = rows
    .flatMap((row, y) => [...row].map((cell, x) => (cell === '1' ? `M${x + quiet} ${y + quiet}h1v1h-1z` : '')))
    .join('');
  return (
    <svg viewBox={`0 0 ${size} ${size}`} shapeRendering="crispEdges" className="w-full h-full" role="img" aria-label="Linking QR code">
      <rect width={size} height={size} fill="#ffffff" />
      <path d={path} fill="#09090b" />
    </svg>
  );
}

function relative(value) {
  const d = value ? new Date(value) : null;
  if (!d || isNaN(d.getTime())) return '';
  const minutes = Math.round((Date.now() - d.getTime()) / 60000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  if (minutes < 60 * 24) return `${Math.round(minutes / 60)}h ago`;
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

export default function ContinuityPanel({ isOpen, onClose, deviceEvent }) {
  const [pairing, setPairing] = useState(null);
  const [devices, setDevices] = useState([]);
  const [error, setError] = useState('');
  const [linked, setLinked] = useState(null);
  const [now, setNow] = useState(Date.now());

  const newCode = useCallback(async () => {
    setError('');
    try {
      const result = await createPairing();
      const receivedAt = Date.now();
      setNow(receivedAt);
      setPairing({ ...result, expiresAt: receivedAt + result.expires_in * 1000 });
    } catch (err) {
      setError(err.message);
    }
  }, []);

  const loadDevices = useCallback(async () => {
    try {
      setDevices(await fetchDevices());
    } catch (err) {
      setError(err.message);
    }
  }, []);

  useEffect(() => {
    if (!isOpen) return undefined;
    setLinked(null);
    newCode();
    loadDevices();
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [isOpen, newCode, loadDevices]);

  useEffect(() => {
    if (!isOpen || !deviceEvent) return;
    loadDevices();
    if (deviceEvent.type === 'device.linked') {
      setLinked(deviceEvent.device);
      newCode(); // the shown code was just used
    }
  }, [deviceEvent]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!isOpen) return null;

  const remaining = pairing ? Math.max(0, Math.round((pairing.expiresAt - now) / 1000)) : 0;
  const expired = pairing && remaining === 0;
  const host = pairing?.url ? new URL(pairing.url).host : '';

  const handleUnlink = async (device) => {
    if (!confirm(`Unlink ${device.name}? It stops working right away.`)) return;
    try {
      await unlinkDevice(device.id);
      loadDevices();
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-6 animate-fade-in"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <section role="dialog" aria-modal="true" aria-labelledby="continuity-title" className="w-full max-w-md dark-popover rounded-2xl text-zinc-200 font-sans">
        <header className="flex items-start justify-between gap-3 p-5 pb-3">
          <div className="flex items-start gap-3">
            <div className="w-10 h-10 rounded-xl bg-[#222226] border border-[#2e2e34] flex items-center justify-center text-blue-400 flex-shrink-0">
              <FiSmartphone className="text-lg" />
            </div>
            <div>
              <h2 id="continuity-title" className="text-sm font-bold text-zinc-100">Continue on iPhone</h2>
              <p className="text-[11px] text-zinc-400 mt-0.5 leading-relaxed">
                Pick up any chat on your iPhone.
              </p>
            </div>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg text-zinc-400 hover:text-white hover:bg-[#2a2a30] transition" title="Close">
            <FiX />
          </button>
        </header>

        <div className="px-5 pb-5 space-y-4">
          {pairing && !pairing.reachable && (
            <div className="flex gap-2.5 rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 text-[11px] leading-relaxed text-amber-200">
              <FiAlertTriangle className="text-amber-400 text-sm flex-shrink-0 mt-0.5" />
              <p>
                Your iPhone can&apos;t connect yet. Restart Open Dots with{' '}
                <code className="font-mono text-amber-100">./scripts/start-mac.sh</code>.
              </p>
            </div>
          )}

          {linked && (
            <div className="flex items-center gap-2 rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-3 text-[11px] text-emerald-300 animate-fade-in">
              <FiCheck className="text-sm flex-shrink-0" />
              <p>{linked.name} is linked.</p>
            </div>
          )}

          <div className="flex gap-4 items-center">
            <div className={`w-40 h-40 flex-shrink-0 rounded-xl overflow-hidden bg-white p-1 shadow-lg transition ${expired ? 'opacity-20 blur-[2px]' : ''}`}>
              {pairing?.qr ? <QrCode rows={pairing.qr.rows} /> : <div className="w-full h-full bg-zinc-200 animate-pulse rounded-lg" />}
            </div>
            <div className="min-w-0 space-y-2">
              <p className="text-xs font-semibold text-zinc-100">Scan with your iPhone</p>
              <p className="text-[11px] text-zinc-400 leading-relaxed">
                Or go to <span className="font-mono text-zinc-300 break-all">{host || '…'}</span> in Safari and enter:
              </p>
              <p className="font-mono text-lg font-semibold tracking-[0.15em] text-white select-all">{pairing?.code || '····-····'}</p>
              {expired ? (
                <button onClick={newCode} className="flex items-center gap-1.5 text-[11px] font-semibold text-blue-400 hover:text-blue-300">
                  <FiRefreshCw /> Get a new code
                </button>
              ) : (
                <p className="text-[10px] text-zinc-500 font-mono">
                  {pairing ? `Expires in ${Math.floor(remaining / 60)}:${String(remaining % 60).padStart(2, '0')}` : 'Getting a code…'}
                </p>
              )}
            </div>
          </div>

          {error && <p role="alert" className="text-[11px] text-rose-400">{error}</p>}

          <div className="border-t border-[#2b2b32] pt-3">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500 mb-2">Linked devices</p>
            {devices.length === 0 ? (
              <p className="text-[11px] text-zinc-500">None yet</p>
            ) : (
              <ul className="space-y-1">
                {devices.map((device) => (
                  <li key={device.id} className="flex items-center justify-between gap-2 rounded-lg px-2 py-1.5 hover:bg-[#222226]">
                    <div className="flex items-center gap-2 min-w-0">
                      <FiSmartphone className="text-zinc-400 flex-shrink-0" />
                      <div className="min-w-0">
                        <p className="text-xs text-zinc-200 truncate">{device.name}</p>
                        <p className="text-[10px] text-zinc-500">
                          Active {relative(device.last_seen_at)}
                        </p>
                      </div>
                    </div>
                    <button onClick={() => handleUnlink(device)} className="text-[11px] text-rose-400 hover:text-rose-300 px-2 py-1 rounded-md hover:bg-rose-500/10">
                      Unlink
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <p className="text-[10px] text-zinc-500 leading-relaxed">
            Your iPhone connects straight to this Mac, with no cloud in between. It can chat and approve actions, but not change settings.
          </p>
        </div>
      </section>
    </div>
  );
}
