'use client';

// The card that creates an assistant: its name, what it's for, and the model it
// calls. Creating it on the server is the caller's job (onCreate).

import React, { useEffect, useRef, useState } from 'react';
import { FiChevronDown } from 'react-icons/fi';
import MascotAvatar from './MascotAvatar';
import ModelMenu, { findModel } from './ModelMenu';

// The first choice: the default model if the provider offers it, else the most
// recent one. Nothing when neither fits, so the person picks.
function initialModel(models, recentIds, defaultModel) {
  if (!models?.length || findModel(models, defaultModel)) return defaultModel || '';
  return recentIds.find((id) => findModel(models, id)) || '';
}

export default function NewAssistantDialog({ isOpen, onClose, onCreate, models, recentIds = [], defaultModel, avatarType }) {
  const [name, setName] = useState('');
  const [role, setRole] = useState('');
  const [model, setModel] = useState('');
  const [menuOpen, setMenuOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const nameRef = useRef(null);
  const modelButtonRef = useRef(null);

  useEffect(() => {
    if (!isOpen) return;
    setName('');
    setRole('');
    setModel(initialModel(models, recentIds, defaultModel));
    setMenuOpen(false);
    setError('');
    setTimeout(() => nameRef.current?.focus(), 0);
    // Only when it opens: the catalog arriving later shouldn't reset a choice.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return undefined;
    const onKey = (event) => {
      if (event.key === 'Escape' && !menuOpen) onClose(); // with the menu open, Escape closes the menu
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [isOpen, menuOpen, onClose]);

  if (!isOpen) return null;

  const chosen = findModel(models, model);
  const canCreate = name.trim() && model && !saving;

  const submit = async (event) => {
    event.preventDefault();
    if (!canCreate) return;
    setSaving(true);
    setError('');
    try {
      await onCreate({ name: name.trim(), role: role.trim(), model });
    } catch (err) {
      setError(err.message || "Couldn't create the assistant.");
      setSaving(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in"
      onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}
    >
      <form
        onSubmit={submit}
        className="w-[440px] max-w-[calc(100vw-32px)] dark-popover rounded-2xl p-5 space-y-4"
        role="dialog"
        aria-modal="true"
        aria-labelledby="new-assistant-title"
      >
        <div className="flex items-center gap-3">
          <MascotAvatar type={avatarType} size="lg" />
          <div className="min-w-0">
            <h2 id="new-assistant-title" className="text-sm font-semibold text-white truncate">
              {name.trim() || 'New assistant'}
            </h2>
            <p className="text-[11px] text-zinc-500">Give it a name and the model it talks with.</p>
          </div>
        </div>

        <div className="space-y-1.5">
          <label htmlFor="assistant-name" className="block text-[11px] font-medium text-zinc-400">Name</label>
          <input
            id="assistant-name"
            ref={nameRef}
            value={name}
            maxLength={40}
            onChange={(event) => setName(event.target.value)}
            placeholder="Atlas"
            className="w-full bg-[#141417] border border-[#2c2c33] rounded-lg px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-blue-500/60"
          />
        </div>

        <div className="space-y-1.5">
          <span className="block text-[11px] font-medium text-zinc-400">Model</span>
          <div className="relative">
            <button
              ref={modelButtonRef}
              type="button"
              onClick={() => setMenuOpen((open) => !open)}
              title={model}
              className={`w-full flex items-center gap-2 bg-[#141417] border rounded-lg px-3 py-2 text-sm text-left transition ${
                menuOpen ? 'border-blue-500/60' : 'border-[#2c2c33] hover:border-zinc-600'
              }`}
            >
              {chosen?.provider && <span className="text-zinc-500 text-xs">{chosen.provider}</span>}
              <span className={`flex-1 min-w-0 truncate ${model ? 'text-zinc-100' : 'text-zinc-600'}`}>
                {chosen?.name || model || 'Pick a model'}
              </span>
              <FiChevronDown className={`text-zinc-500 transition-transform ${menuOpen ? 'rotate-180' : ''}`} />
            </button>
            {menuOpen && (
              <ModelMenu
                models={models}
                recentIds={recentIds}
                value={model}
                onSelect={setModel}
                onClose={() => setMenuOpen(false)}
                anchorRef={modelButtonRef}
                cascade="right"
              />
            )}
          </div>
        </div>

        <div className="space-y-1.5">
          <label htmlFor="assistant-role" className="block text-[11px] font-medium text-zinc-400">
            What it’s for <span className="text-zinc-600">(optional)</span>
          </label>
          <input
            id="assistant-role"
            value={role}
            maxLength={60}
            onChange={(event) => setRole(event.target.value)}
            placeholder="Research and writing"
            className="w-full bg-[#141417] border border-[#2c2c33] rounded-lg px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-blue-500/60"
          />
        </div>

        {error && <p className="text-xs text-red-400">{error}</p>}

        <div className="flex justify-end gap-2 pt-1">
          <button type="button" onClick={onClose} className="px-3.5 py-1.5 rounded-lg text-xs font-medium text-zinc-400 hover:text-white hover:bg-[#26262c] transition">
            Cancel
          </button>
          <button
            type="submit"
            disabled={!canCreate}
            className="px-3.5 py-1.5 rounded-lg text-xs font-semibold bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-40 disabled:hover:bg-blue-600 transition"
          >
            {saving ? 'Creating…' : 'Create'}
          </button>
        </div>
      </form>
    </div>
  );
}
