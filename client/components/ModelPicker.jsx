'use client';

import React, { useRef, useState } from 'react';
import { FiChevronDown } from 'react-icons/fi';
import ModelMenu, { findModel } from './ModelMenu';

// The chat header's model button: shows the assistant's model and changes it.
export default function ModelPicker({ currentModel, onSelectModel, models, recentIds }) {
  const [isOpen, setIsOpen] = useState(false);
  const anchorRef = useRef(null);
  const current = findModel(models, currentModel);
  // An assistant can name a model its provider no longer offers (or never did,
  // after switching providers); its replies would fail, so say so.
  const unknown = Boolean(models?.length && currentModel && !current);

  return (
    <div className="relative z-50">
      <button
        ref={anchorRef}
        type="button"
        onClick={() => setIsOpen((open) => !open)}
        title={unknown ? `${currentModel} isn't offered by your model provider. Pick another.` : currentModel}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-[#1c1c20] hover:bg-[#242429] border border-[#2b2b32] text-xs text-zinc-200 transition shadow-sm font-medium"
      >
        {unknown && <span className="w-1.5 h-1.5 rounded-full bg-amber-400 flex-shrink-0" />}
        {current?.provider && <span className="text-zinc-500 max-w-[90px] truncate">{current.provider}</span>}
        <span className="max-w-[160px] truncate">{current?.name || currentModel || 'Pick a model'}</span>
        <FiChevronDown className={`text-zinc-400 text-xs transition-transform duration-200 ${isOpen ? 'rotate-180' : ''}`} />
      </button>

      {isOpen && (
        <ModelMenu
          models={models}
          recentIds={recentIds}
          value={currentModel}
          onSelect={onSelectModel}
          onClose={() => setIsOpen(false)}
          anchorRef={anchorRef}
          cascade="left"
        />
      )}
    </div>
  );
}
