'use client';

// The model menu: recent models first, then providers that open, one level at a
// time, into their models. Used by the new-assistant dialog and the chat header.
// It only picks a model ID; saving it on an assistant is the caller's job.

import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { FiCheck, FiChevronRight } from 'react-icons/fi';

const MAX_RECENT = 5;
const MAX_HEIGHT = 380;
const EDGE_GAP = 16; // keep this far from the window's edge
// Moving the pointer diagonally into the open list crosses other providers;
// waiting this long before switching keeps the list from jumping.
const HOVER_SWITCH_MS = 120;

export function groupByProvider(models) {
  const groups = new Map();
  for (const model of models || []) {
    if (model.is_available === false) continue;
    const name = model.provider || 'Other';
    if (!groups.has(name)) groups.set(name, []);
    groups.get(name).push(model);
  }
  return [...groups.entries()].map(([name, list]) => ({ name, models: list }));
}

export function findModel(models, id) {
  return (models || []).find((model) => model.id === id) || null;
}

function Row({ selected, onClick, onMouseEnter, open, children, title }) {
  return (
    <button
      type="button"
      role="menuitem"
      title={title}
      onClick={onClick}
      onMouseEnter={onMouseEnter}
      className={`w-full flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-left text-xs transition ${
        open ? 'bg-[#26262c] text-white' : selected ? 'text-blue-300 hover:bg-[#222227]' : 'text-zinc-300 hover:bg-[#222227] hover:text-white'
      }`}
    >
      {children}
    </button>
  );
}

function SectionLabel({ children }) {
  return <p className="px-2.5 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">{children}</p>;
}

export default function ModelMenu({ models, recentIds = [], value, onSelect, onClose, anchorRef, cascade = 'right' }) {
  const providers = useMemo(() => groupByProvider(models), [models]);
  const [openProvider, setOpenProvider] = useState(null);
  // Below the button when it fits, else above; never past the window's edge.
  const [placement, setPlacement] = useState({ up: false, maxHeight: MAX_HEIGHT });
  const menuRef = useRef(null);
  const hoverTimer = useRef(null);

  const recent = useMemo(() => {
    // Only models the provider still offers; with no list at all, show them as they are.
    const known = models?.length ? recentIds.map((id) => findModel(models, id)).filter(Boolean) : recentIds.map((id) => ({ id, name: id }));
    return known.slice(0, MAX_RECENT);
  }, [models, recentIds]);

  useEffect(() => {
    const onKey = (event) => {
      if (event.key !== 'Escape') return;
      if (openProvider) setOpenProvider(null);
      else onClose();
    };
    const onPointer = (event) => {
      if (menuRef.current?.contains(event.target) || anchorRef?.current?.contains(event.target)) return;
      onClose();
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('mousedown', onPointer);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('mousedown', onPointer);
      clearTimeout(hoverTimer.current);
    };
  }, [openProvider, onClose, anchorRef]);

  useLayoutEffect(() => {
    const rect = anchorRef?.current?.getBoundingClientRect();
    if (!rect) return;
    const below = window.innerHeight - rect.bottom - EDGE_GAP;
    const above = rect.top - EDGE_GAP;
    const up = below < 260 && above > below;
    setPlacement({ up, maxHeight: Math.max(160, Math.min(MAX_HEIGHT, (up ? above : below) - 8)) });
  }, [anchorRef]);

  const openSoon = (name) => {
    clearTimeout(hoverTimer.current);
    hoverTimer.current = setTimeout(() => setOpenProvider(name), HOVER_SWITCH_MS);
  };
  const openNow = (name) => {
    clearTimeout(hoverTimer.current);
    setOpenProvider(name);
  };
  const pick = (id) => {
    onSelect(id);
    onClose();
  };

  const opened = providers.find((provider) => provider.name === openProvider);
  const selectedProvider = findModel(models, value)?.provider;

  return (
    <div
      ref={menuRef}
      role="menu"
      className={`absolute z-50 flex gap-1.5 animate-fade-in ${placement.up ? 'bottom-full mb-2 items-end' : 'top-full mt-2 items-start'} ${
        cascade === 'left' ? 'right-0 flex-row-reverse' : 'left-0'
      }`}
    >
      <div className="w-60 overflow-y-auto dark-popover dark-scroll rounded-xl p-1.5" style={{ maxHeight: placement.maxHeight }}>
        {recent.length > 0 && (
          <>
            <SectionLabel>Recent</SectionLabel>
            {recent.map((model) => (
              <Row key={model.id} selected={model.id === value} title={model.id} onClick={() => pick(model.id)} onMouseEnter={() => openSoon(null)}>
                <span className="flex-1 min-w-0 truncate">{model.name}</span>
                {model.provider && <span className="text-[10px] text-zinc-500 truncate max-w-[80px]">{model.provider}</span>}
                {model.id === value && <FiCheck className="flex-shrink-0 text-blue-300" />}
              </Row>
            ))}
            <div className="my-1.5 h-px bg-[#2b2b32]" />
          </>
        )}

        <SectionLabel>Providers</SectionLabel>
        {providers.length === 0 && (
          <p className="px-2.5 py-2 text-[11px] leading-relaxed text-zinc-500">
            Your model provider doesn’t list its models. Set it up in Settings → Model provider.
          </p>
        )}
        {providers.map((provider) => (
          <Row
            key={provider.name}
            open={provider.name === openProvider}
            onClick={() => openNow(provider.name)}
            onMouseEnter={() => openSoon(provider.name)}
          >
            <span className="w-5 h-5 rounded-md bg-[#2a2a31] text-[10px] font-bold text-zinc-300 flex items-center justify-center flex-shrink-0">
              {provider.name.slice(0, 1).toUpperCase()}
            </span>
            <span className={`flex-1 min-w-0 truncate ${provider.name === selectedProvider ? 'text-blue-300' : ''}`}>{provider.name}</span>
            <span className="text-[10px] text-zinc-500">{provider.models.length}</span>
            <FiChevronRight className={`flex-shrink-0 text-zinc-500 ${cascade === 'left' ? 'rotate-180' : ''}`} />
          </Row>
        ))}
      </div>

      {opened && (
        <div
          key={opened.name}
          onMouseEnter={() => clearTimeout(hoverTimer.current)}
          className="w-64 overflow-y-auto dark-popover dark-scroll rounded-xl p-1.5 animate-step-in"
          style={{ maxHeight: placement.maxHeight }}
        >
          <SectionLabel>{opened.name}</SectionLabel>
          {opened.models.map((model) => (
            <Row key={model.id} selected={model.id === value} title={model.id} onClick={() => pick(model.id)}>
              <span className="flex-1 min-w-0 truncate">{model.name}</span>
              {model.id === value && <FiCheck className="flex-shrink-0 text-blue-300" />}
            </Row>
          ))}
        </div>
      )}
    </div>
  );
}
