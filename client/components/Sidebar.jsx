'use client';

import React, { useState, useEffect, useRef } from 'react';
import { FiSearch, FiPlus, FiSettings, FiActivity, FiLogOut, FiSmartphone, FiTrash2, FiUserPlus } from 'react-icons/fi';
import MascotAvatar from './MascotAvatar';
import UpdatePill from './UpdatePill';
import { isDeviceOrigin } from '../lib/liveChat';

function formatRowTime(value) {
  const d = value ? new Date(value) : null;
  if (!d || isNaN(d.getTime())) return '';
  const now = new Date();
  if (d.toDateString() === now.toDateString()) {
    return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
  }
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function plainPreview(text) {
  return String(text || '').replace(/```[\s\S]*?(```|$)/g, ' ').replace(/[*_`#>]+/g, '').replace(/\s+/g, ' ').trim();
}

export default function Sidebar({
  onLogout,
  bots,
  threads,
  activeThreadId,
  draftBotId,
  userName,
  onSelectThread,
  onNewChat,
  onDeleteThread,
  activeTab,
  onSelectTab,
  onOpenSettings,
  onOpenNewBot,
  onOpenContinuity,
  connection,
  update,
  onInstallUpdate,
}) {
  const [searchTerm, setSearchTerm] = useState('');
  const [isNewChatMenuOpen, setIsNewChatMenuOpen] = useState(false);
  const menuRef = useRef(null);
  // userName comes from Dashboard (synced with AppSettingsDrawer in real-time)
  const displayName = userName || 'You';

  useEffect(() => {
    if (!isNewChatMenuOpen) return undefined;
    const close = (event) => {
      if (!menuRef.current?.contains(event.target)) setIsNewChatMenuOpen(false);
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [isNewChatMenuOpen]);

  const botIndex = (botId) => bots.findIndex((b) => b.id === botId);
  const avatarFor = (botId) => (botIndex(botId) % 2 === 1 ? 'pink' : 'blue');
  const botName = (botId) => bots.find((b) => b.id === botId)?.name || 'Assistant';

  const rows = threads.map((thread) => {
    const last = thread.last_message;
    let subtitle = 'No messages yet';
    if (last) {
      const text = plainPreview(last.text) || (last.has_image ? 'Photo' : '');
      subtitle = last.sender === 'user' ? `You: ${text}` : text;
    }
    return {
      id: thread.id,
      name: thread.title || botName(thread.bot_id),
      subtitle,
      botName: botName(thread.bot_id),
      avatarType: avatarFor(thread.bot_id),
      time: formatRowTime(thread.updated_at),
      status: thread.status,
      fromDevice: isDeviceOrigin(thread.last_origin) ? thread.last_origin : null,
    };
  });

  const term = searchTerm.toLowerCase();
  const filteredRows = rows.filter(
    (row) =>
      row.name.toLowerCase().includes(term) ||
      row.subtitle.toLowerCase().includes(term) ||
      row.botName.toLowerCase().includes(term)
  );

  const startChat = (botId) => {
    setIsNewChatMenuOpen(false);
    onNewChat(botId);
  };

  return (
    <aside className="w-72 h-screen dark-sidebar flex flex-col justify-between select-none flex-shrink-0 text-zinc-300 font-sans">
      {/* Top Header & Search Area */}
      <div className="p-3.5 space-y-3">
        {/* Traffic Light Dots & Plus Button Header */}
        <div className="flex items-center justify-between pt-1 px-1">
          <div className="flex items-center space-x-2">
            <span className="w-3 h-3 rounded-full bg-[#ff5f57] block border border-[#e0443e]/40 cursor-pointer hover:opacity-80 transition" />
            <span className="w-3 h-3 rounded-full bg-[#febc2e] block border border-[#d8a025]/40 cursor-pointer hover:opacity-80 transition" />
            <span className="w-3 h-3 rounded-full bg-[#28c840] block border border-[#1fa031]/40 cursor-pointer hover:opacity-80 transition" />
          </div>

          <div className="flex items-center gap-2">
          <UpdatePill update={update} onInstall={onInstallUpdate} onOpenSettings={onOpenSettings} />
          <div className="relative" ref={menuRef}>
            <button
              suppressHydrationWarning={true}
              onClick={() => setIsNewChatMenuOpen((open) => !open)}
              title="New Chat"
              className="text-zinc-400 hover:text-white transition p-1 rounded-md hover:bg-[#222226]"
            >
              <FiPlus className="text-lg" />
            </button>

            {isNewChatMenuOpen && (
              <div className="absolute right-0 top-9 z-30 w-64 dark-popover rounded-xl p-1.5 animate-fade-in">
                <p className="px-2 pt-1 pb-1.5 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">New chat with</p>
                {bots.map((bot, idx) => (
                  <button
                    key={bot.id}
                    onClick={() => startChat(bot.id)}
                    className="w-full flex items-center gap-2.5 px-2 py-1.5 rounded-lg text-left hover:bg-[#27272a] transition"
                  >
                    <MascotAvatar type={idx % 2 === 1 ? 'pink' : 'blue'} size="sm" />
                    <div className="min-w-0">
                      <p className="text-xs font-semibold text-zinc-200 truncate">{bot.name}</p>
                      <p className="text-[10px] text-zinc-500 truncate">{bot.role}</p>
                    </div>
                  </button>
                ))}
                <div className="my-1 h-px bg-[#2b2b32]" />
                <button
                  onClick={() => { setIsNewChatMenuOpen(false); onOpenNewBot(); }}
                  className="w-full flex items-center gap-2.5 px-2 py-1.5 rounded-lg text-xs text-zinc-300 hover:text-white hover:bg-[#27272a] transition"
                >
                  <FiUserPlus className="text-sm" /> New assistant…
                </button>
              </div>
            )}
          </div>
          </div>
        </div>

        {/* Rounded Search Bar */}
        <div className="relative">
          <FiSearch className="absolute left-3 top-2.5 text-zinc-500 text-xs" />
          <input
            suppressHydrationWarning={true}
            type="text"
            placeholder="Search"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full bg-[#222225] border border-[#2c2c30] rounded-xl pl-8 pr-3 py-1.5 text-xs text-zinc-200 placeholder-zinc-500 focus:outline-none focus:border-zinc-500 transition"
          />
        </div>
      </div>

      {/* Conversation List */}
      <div className="flex-1 overflow-y-auto px-2 space-y-1.5">
        {draftBotId && (
          <div className="p-2.5 rounded-xl flex items-start gap-3 bg-[#27272a] text-white shadow-sm border border-[#34343a]">
            <MascotAvatar type={avatarFor(draftBotId)} size="md" />
            <div className="flex-1 min-w-0 pt-0.5">
              <h3 className="text-xs font-semibold truncate text-white">New chat</h3>
              <p className="text-[11px] truncate mt-0.5 text-zinc-400">{botName(draftBotId)}</p>
            </div>
          </div>
        )}

        {filteredRows.map((row) => {
          const isActive = activeThreadId === row.id;

          return (
            <div
              key={row.id}
              onClick={() => onSelectThread(row.id)}
              className={`group p-2.5 rounded-xl cursor-pointer transition-all duration-150 flex items-start gap-3 ${
                isActive
                  ? 'bg-[#27272a] text-white shadow-sm border border-[#34343a]'
                  : 'hover:bg-[#1c1c20] text-zinc-400 border border-transparent'
              }`}
            >
              <MascotAvatar type={row.avatarType} size="md" />

              <div className="flex-1 min-w-0 pt-0.5">
                <div className="flex items-center justify-between gap-1">
                  <h3 className={`text-xs font-semibold truncate ${isActive ? 'text-white' : 'text-zinc-200'}`}>
                    {row.name}
                  </h3>
                  <span className="flex items-center gap-1 flex-shrink-0">
                    {row.fromDevice && (
                      <FiSmartphone className="text-[10px] text-blue-400" title={`Sent from ${row.fromDevice}`} />
                    )}
                    {row.time && (
                      <span className="text-[10px] text-zinc-400 font-normal ml-1 group-hover:hidden">
                        {row.time}
                      </span>
                    )}
                    {row.status === 'idle' && (
                      <button
                        suppressHydrationWarning={true}
                        onClick={(e) => {
                          e.stopPropagation();
                          if (confirm(`Delete "${row.name}"? This can't be undone.`)) {
                            onDeleteThread(row.id);
                          }
                        }}
                        className="hidden group-hover:block text-zinc-500 hover:text-rose-400 transition"
                        title="Delete chat"
                      >
                        <FiTrash2 className="text-[11px]" />
                      </button>
                    )}
                  </span>
                </div>

                {row.status === 'waiting' ? (
                  <p className="text-[11px] truncate mt-0.5 text-amber-400">Needs your approval</p>
                ) : row.status === 'running' ? (
                  <p className="text-[11px] truncate mt-0.5 text-blue-400">Replying…</p>
                ) : (
                  <p className="text-[11px] truncate mt-0.5 text-zinc-400 group-hover:text-zinc-300">
                    {row.subtitle}
                  </p>
                )}
              </div>
            </div>
          );
        })}

        {rows.length === 0 && !draftBotId && (
          <p className="px-3 py-6 text-center text-[11px] text-zinc-500">
            No chats yet
          </p>
        )}
      </div>

      {/* Bottom Sidebar Footer */}
      <div className="p-3 space-y-2 border-t border-[#1f1f23]">
        <button
          suppressHydrationWarning={true}
          onClick={onOpenContinuity}
          className="w-full flex items-center gap-2 px-2 py-1 rounded-lg text-xs font-medium text-zinc-300 hover:text-white hover:bg-[#1e1e22] transition"
        >
          <FiSmartphone className="text-sm text-blue-400" />
          <span>Continue on iPhone</span>
        </button>

        {/* Plugins Section */}
        <button
          suppressHydrationWarning={true}
          onClick={() => onSelectTab && onSelectTab('marketplace')}
          className={`w-full flex items-center gap-2 px-2 py-1 rounded-lg text-xs font-medium transition ${
            activeTab === 'marketplace'
              ? 'text-white bg-[#1e1e22]'
              : 'text-zinc-300 hover:text-white hover:bg-[#1e1e22]'
          }`}
        >
          <span className="text-sm">🧩</span>
          <span>Plugins</span>
        </button>

        <button
          suppressHydrationWarning={true}
          onClick={() => onSelectTab && onSelectTab('audit')}
          className={`w-full flex items-center gap-2 px-2 py-1 rounded-lg text-xs font-medium transition ${
            activeTab === 'audit'
              ? 'text-white bg-[#1e1e22]'
              : 'text-zinc-300 hover:text-white hover:bg-[#1e1e22]'
          }`}
        >
          <FiActivity className="text-sm text-cyan-400" />
          <span>Audit trail</span>
        </button>

        <button onClick={onLogout} className="w-full flex items-center gap-2 px-2 py-1 rounded-lg text-xs text-zinc-300 hover:text-white hover:bg-[#1e1e22]">
          <FiLogOut /> Sign out
        </button>

        {/* Profile Row */}
        <div className="flex items-center justify-between pt-1">
          <button
            suppressHydrationWarning={true}
            onClick={onOpenSettings}
            className="flex items-center gap-2 px-2 py-1 rounded-lg text-xs font-medium text-zinc-300 hover:text-white hover:bg-[#1e1e22] transition"
          >
            <div className="w-5 h-5 rounded-full bg-[#2a2a2e] flex items-center justify-center text-[10px] text-zinc-400 font-bold border border-[#333338]">
              {displayName.charAt(0).toUpperCase()}
            </div>
            <span>{displayName}</span>
          </button>

          <div className="flex items-center gap-1">
            {connection !== 'live' && (
              <span className="text-[10px] text-amber-400">Reconnecting…</span>
            )}
            <button
              suppressHydrationWarning={true}
              onClick={onOpenSettings}
              className="p-2 text-zinc-400 hover:text-zinc-200 hover:bg-[#1e1e22] rounded-lg transition"
              title="Settings"
            >
              <FiSettings className="text-sm" />
            </button>
          </div>
        </div>
      </div>
    </aside>
  );
}
