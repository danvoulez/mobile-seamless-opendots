'use client';

import React, { useState, useEffect, useRef, useCallback } from 'react';
import Sidebar from './Sidebar';
import ChatWindow from './ChatWindow';
import ComputerPanel from './ComputerPanel';
import Marketplace from './Marketplace';
import AuditPanel from './AuditPanel';
import AppSettingsDrawer from './AppSettingsDrawer';
import ContinuityPanel from './ContinuityPanel';

import {
  fetchBots,
  fetchModels,
  fetchSettings,
  fetchThreads,
  fetchThread,
  createThread,
  deleteThread,
  postThreadMessage,
  respondApproval,
  subscribeToEvents,
  createBot,
  updateBot
} from '../lib/api';
import { applyChatEvent, emptyChat, mergeSnapshot, upsertMessage, upsertThread } from '../lib/liveChat';

export default function Dashboard({ onLogout }) {
  const [bots, setBots] = useState([]);
  const [models, setModels] = useState([]);
  const [threads, setThreads] = useState([]);
  const [activeThreadId, setActiveThreadId] = useState(null);
  const [draftBotId, setDraftBotId] = useState(null); // a new chat not sent yet
  const [chat, setChat] = useState(emptyChat);
  const [activeTab, setActiveTab] = useState('chat'); // 'chat' | 'computer' | 'marketplace' | 'audit'
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isContinuityOpen, setIsContinuityOpen] = useState(false);
  const [deviceEvent, setDeviceEvent] = useState(null);
  const [connection, setConnection] = useState('reconnecting');
  const [defaultModel, setDefaultModel] = useState('gpt-5-mini');
  const [userName, setUserName] = useState(() => {
    if (typeof window !== 'undefined') {
      return localStorage.getItem('open_dots_user_name') || 'You';
    }
    return 'You';
  });
  const activeThreadRef = useRef(null);

  const activeThread = threads.find((t) => t.id === activeThreadId) || null;
  const activeBotId = activeThread?.bot_id || draftBotId;
  const activeBot = bots.find((b) => b.id === activeBotId) || bots[0];

  const selectThread = useCallback((threadId) => {
    setActiveTab('chat');
    if (threadId === activeThreadRef.current) return;
    activeThreadRef.current = threadId;
    setActiveThreadId(threadId);
    setDraftBotId(null);
    setChat({ ...emptyChat, loading: Boolean(threadId) });
  }, []);

  const startDraft = useCallback((botId) => {
    activeThreadRef.current = null;
    setActiveThreadId(null);
    setDraftBotId(botId);
    setChat(emptyChat);
    setActiveTab('chat');
  }, []);

  // Streaming events can ask for a reload many times a second; run one at a
  // time, plus one more if something asked again meanwhile.
  const loadingRef = useRef(null); // { threadId, again }
  const loadThread = useCallback(async (threadId) => {
    if (loadingRef.current?.threadId === threadId) {
      loadingRef.current.again = true;
      return;
    }
    const load = { threadId, again: false };
    loadingRef.current = load;
    try {
      do {
        load.again = false;
        try {
          const detail = await fetchThread(threadId);
          if (activeThreadRef.current !== threadId) return;
          setChat((prev) => mergeSnapshot(prev, detail));
          setThreads((prev) => upsertThread(prev, detail.thread));
        } catch (err) {
          if (activeThreadRef.current !== threadId) return;
          console.error('Failed to load conversation:', err);
          setChat((prev) => ({ ...prev, loading: false }));
        }
      } while (load.again && activeThreadRef.current === threadId);
    } finally {
      if (loadingRef.current === load) loadingRef.current = null;
    }
  }, []);

  const refresh = useCallback(async () => {
    const latest = await fetchThreads();
    setThreads(latest);
    if (activeThreadRef.current) loadThread(activeThreadRef.current);
  }, [loadThread]);

  // Initial Data Fetch
  useEffect(() => {
    async function initData() {
      try {
        const [botsData, modelsData, settingsData, threadsData] = await Promise.all([
          fetchBots(), fetchModels(), fetchSettings(), fetchThreads(),
        ]);
        setBots(botsData);
        setModels(modelsData);
        setThreads(threadsData);
        if (settingsData?.default_model) {
          setDefaultModel(settingsData.default_model);
        }
        if (threadsData.length > 0) {
          selectThread(threadsData[0].id);
        } else if (botsData.length > 0) {
          startDraft(botsData[0].id);
        }
      } catch (err) {
        console.error('Initialization error:', err);
      }
    }
    initData();
  }, [selectThread, startDraft]);

  useEffect(() => {
    if (activeThreadId) loadThread(activeThreadId);
  }, [activeThreadId, loadThread]);

  // Live events from this computer and every linked device.
  useEffect(() => subscribeToEvents((event) => {
    switch (event.type) {
      case 'hello':
      case 'resync':
        refresh();
        return;
      case 'thread.created':
      case 'thread.updated':
        setThreads((prev) => upsertThread(prev, event.thread));
        return;
      case 'thread.deleted':
        setThreads((prev) => prev.filter((t) => t.id !== event.threadId));
        if (activeThreadRef.current === event.threadId) {
          activeThreadRef.current = null;
          setActiveThreadId(null);
          setChat(emptyChat);
        }
        return;
      case 'device.linked':
      case 'device.unlinked':
        setDeviceEvent({ ...event, at: Date.now() });
        return;
      default:
        break;
    }
    if (event.threadId && event.threadId === activeThreadRef.current) {
      setChat((prev) => applyChatEvent(prev, event));
    }
  }, setConnection), [refresh]);

  useEffect(() => {
    if (chat.needsReload && activeThreadRef.current) {
      setChat((prev) => ({ ...prev, needsReload: false }));
      loadThread(activeThreadRef.current);
    }
  }, [chat.needsReload, loadThread]);

  // After deleting the open conversation, land on the next one (or a new chat).
  useEffect(() => {
    if (activeThreadId || draftBotId || bots.length === 0) return;
    if (threads.length > 0) selectThread(threads[0].id);
    else startDraft(bots[0].id);
  }, [activeThreadId, draftBotId, threads, bots, selectThread, startDraft]);

  const handleSend = async ({ text, imageUrl, previewUrl, model }) => {
    const clientId = `c-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
    setChat((prev) => ({
      ...prev,
      messages: [...prev.messages, {
        id: clientId,
        client_id: clientId,
        sender: 'user',
        text,
        image_url: previewUrl || imageUrl,
        created_at: new Date().toISOString(),
        origin: 'Mac',
        pending: true,
      }],
    }));

    try {
      let threadId = activeThreadRef.current;
      if (!threadId) {
        const thread = await createThread(activeBot.id);
        threadId = thread.id;
        activeThreadRef.current = threadId;
        setThreads((prev) => upsertThread(prev, thread));
        setActiveThreadId(threadId);
        setDraftBotId(null);
      }
      const result = await postThreadMessage(threadId, { text, imageUrl, model, clientId });
      if (activeThreadRef.current !== threadId) return;
      setChat((prev) => ({
        ...prev,
        messages: upsertMessage(prev.messages, result.message),
        turn: prev.turn?.botMsgId === result.turn.botMsgId ? prev.turn : result.turn,
      }));
    } catch (err) {
      setChat((prev) => ({ ...prev, messages: prev.messages.filter((m) => m.client_id !== clientId) }));
      throw err;
    }
  };

  const handleRespondApproval = async (requestId, action) => {
    await respondApproval(requestId, action);
  };

  const handleDeleteThread = async (threadId) => {
    try {
      await deleteThread(threadId);
    } catch (err) {
      alert(err.message);
    }
  };

  const handleUpdateBotModel = async (botId, newModel) => {
    try {
      const updated = await updateBot(botId, { model: newModel });
      setBots((prev) => prev.map((b) => (b.id === botId ? updated : b)));
    } catch (err) {
      console.error('Failed to update bot model:', err);
    }
  };

  const handleCreateNewBot = async () => {
    const name = prompt('Enter Bot Name:', 'New Assistant');
    if (!name) return;
    const role = prompt('Enter Role:', 'General Intelligence');
    const model = prompt('Enter Model:', defaultModel);

    try {
      const newBot = await createBot({
        name,
        role: role || 'AI Assistant',
        model: model || defaultModel,
        description: `Custom assistant configured to use ${model || defaultModel}.`,
        avatar: '🤖',
        system_prompt: `You are ${name}, a helpful AI assistant.`
      });
      setBots((prev) => [...prev, newBot]);
      startDraft(newBot.id);
    } catch (err) {
      console.error('Failed to create bot:', err);
    }
  };

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-[#09090b] text-zinc-100 font-sans">
      {/* Sidebar Navigation & Conversations */}
      <Sidebar
        onLogout={onLogout}
        bots={bots}
        threads={threads}
        activeThreadId={activeThreadId}
        draftBotId={draftBotId}
        userName={userName}
        onSelectThread={selectThread}
        onNewChat={startDraft}
        onDeleteThread={handleDeleteThread}
        activeTab={activeTab}
        onSelectTab={setActiveTab}
        onOpenSettings={() => setIsSettingsOpen(!isSettingsOpen)}
        onOpenNewBot={handleCreateNewBot}
        onOpenContinuity={() => setIsContinuityOpen(true)}
        connection={connection}
      />

      {/* Main Workspace Display Area */}
      <main className="flex-1 flex flex-col h-screen overflow-hidden relative">
        {activeTab === 'chat' && (
          <ChatWindow
            bot={activeBot}
            botIndex={bots.findIndex((b) => b.id === activeBot?.id)}
            thread={activeThread}
            models={models}
            messages={chat.messages}
            turn={chat.turn}
            loading={chat.loading}
            onSend={handleSend}
            onRespondApproval={handleRespondApproval}
            onUpdateBotModel={handleUpdateBotModel}
            onToggleComputer={() => setActiveTab('computer')}
            defaultModel={defaultModel}
          />
        )}

        {activeTab === 'computer' && (
          <ComputerPanel bot={activeBot} onBackToChat={() => setActiveTab('chat')} />
        )}

        {activeTab === 'marketplace' && (
          <Marketplace onOpenSettings={() => setIsSettingsOpen(true)} />
        )}

        {activeTab === 'audit' && <AuditPanel />}
      </main>

      {/* Right Side App Settings Drawer Panel */}
      <AppSettingsDrawer
        models={models}
        isOpen={isSettingsOpen}
        onClose={() => setIsSettingsOpen(false)}
        currentModel={defaultModel}
        onUpdateDefaultModel={async (newModel) => {
          setDefaultModel(newModel);
          setModels(await fetchModels());
        }}
        onProfileUpdate={(name) => setUserName(name || 'You')}
      />

      <ContinuityPanel
        isOpen={isContinuityOpen}
        onClose={() => setIsContinuityOpen(false)}
        deviceEvent={deviceEvent}
      />
    </div>
  );
}
