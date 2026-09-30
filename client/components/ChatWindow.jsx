'use client';

import React, { useState, useRef, useEffect } from 'react';
import MessageItem from './MessageItem';
import ActionStep from './ActionStep';
import ModelPicker from './ModelPicker';
import MascotAvatar from './MascotAvatar';
import { FiPlus, FiMic, FiMicOff, FiMonitor, FiX } from 'react-icons/fi';
import { uploadImage } from '../lib/api';
import { turnSteps } from '../lib/liveChat';

function formatHeaderDate(msgs) {
  const firstWithDate = msgs?.find((m) => m.created_at);
  if (!firstWithDate || !firstWithDate.created_at) {
    return 'Today';
  }
  const d = new Date(firstWithDate.created_at);
  if (isNaN(d.getTime())) return 'Today';

  const now = new Date();
  if (d.toDateString() === now.toDateString()) {
    return 'Today';
  }

  const yesterday = new Date();
  yesterday.setDate(now.getDate() - 1);
  if (d.toDateString() === yesterday.toDateString()) {
    return 'Yesterday';
  }

  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

function formatMsgTime(createdAt) {
  const d = createdAt ? new Date(createdAt) : null;
  if (!d || isNaN(d.getTime())) return '';
  return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
}

export default function ChatWindow({
  bot,
  botIndex = 0,
  thread,
  models,
  messages,
  turn,
  loading,
  onSend,
  onRespondApproval,
  onUpdateBotModel,
  onToggleComputer,
  defaultModel,
}) {
  const [inputPrompt, setInputPrompt] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [sendError, setSendError] = useState('');
  const [isListening, setIsListening] = useState(false);
  const [activeModel, setActiveModel] = useState(bot?.model || defaultModel || 'gpt-5-mini');
  const [selectedImage, setSelectedImage] = useState(null);
  const messagesEndRef = useRef(null);
  const fileInputRef = useRef(null);

  const botTitle = bot?.name || 'Open Dots Assistant';
  const avatarType = bot?.isError ? 'warning' : botIndex % 2 === 1 ? 'pink' : 'blue';
  const isStreaming = turn?.status === 'running';
  const needsApproval = isStreaming && turn.approvals?.some((approval) => approval.status === 'pending');

  // Initial welcome greeting fallback for the active bot
  const defaultInitialMessages = [
    {
      id: 'msg-intro',
      sender: 'bot',
      text: `Hi, I'm **${botTitle}**. What can I help with?`,
      isError: false,
    },
  ];

  const activeMessages = messages && messages.length > 0 ? messages : defaultInitialMessages;

  useEffect(() => {
    if (bot?.model) {
      setActiveModel(bot.model);
    } else if (defaultModel) {
      setActiveModel(defaultModel);
    }
  }, [bot, defaultModel]);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [activeMessages, turn]);

  useEffect(() => {
    setSendError('');
  }, [thread?.id]);

  const handleModelChange = (newModel) => {
    setActiveModel(newModel);
    if (onUpdateBotModel && bot?.id) {
      onUpdateBotModel(bot.id, newModel);
    }
  };

  const handleApprovalResponse = async (requestId, action) => {
    await onRespondApproval(requestId, action);
  };

  const handleImageSelect = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    // Strict IMAGE ONLY validation
    if (!file.type.startsWith('image/')) {
      alert('Only image files (JPEG, PNG, WEBP, GIF, AVIF) are allowed.');
      return;
    }

    const previewUrl = URL.createObjectURL(file);
    setSelectedImage({ file, previewUrl, isUploading: true, uploadedUrl: null, error: null });

    try {
      const res = await uploadImage(file);
      setSelectedImage((prev) => (prev ? { ...prev, isUploading: false, uploadedUrl: res.url } : null));
    } catch (err) {
      console.error('Failed to upload image:', err);
      setSelectedImage((prev) => (prev ? { ...prev, isUploading: false, error: err.message } : null));
    }
  };

  const handleSendMessage = async (e) => {
    e?.preventDefault();
    if ((!inputPrompt.trim() && !selectedImage) || isStreaming || isSending) return;

    const userText = inputPrompt;
    const currentSelected = selectedImage;

    setInputPrompt('');
    setSelectedImage(null);
    setSendError('');
    setIsSending(true);

    let finalImageUrl = currentSelected?.uploadedUrl || null;

    try {
      // Ensure image upload finishes before dispatching to the inference backend
      if (currentSelected && !finalImageUrl) {
        const res = await uploadImage(currentSelected.file);
        finalImageUrl = res.url;
      }
      await onSend({
        text: userText,
        imageUrl: finalImageUrl,
        previewUrl: currentSelected?.previewUrl,
        model: activeModel,
      });
    } catch (err) {
      console.error('Send message error:', err);
      setInputPrompt(userText);
      setSendError(err.message || "Couldn't send. Try again.");
    } finally {
      setIsSending(false);
    }
  };

  // Messages, "Continued on iPhone" markers, and the current turn's steps,
  // placed just before the reply they belong to.
  const renderThread = () => {
    const steps = turnSteps(turn);
    const turnCards = steps.length ? [
      <div key="steps" className="py-0.5">
        {steps.map((step, index) => (
          <ActionStep
            key={step.key}
            approval={step.approval}
            event={step.event}
            preview={step.preview}
            last={index === steps.length - 1}
            onRespond={handleApprovalResponse}
          />
        ))}
      </div>,
    ] : [];
    const items = [];
    let lastOrigin = null;
    let cardsPlaced = false;

    for (const msg of activeMessages) {
      if (msg.sender === 'user' && msg.origin) {
        if (lastOrigin && msg.origin !== lastOrigin) {
          items.push(
            <div key={`handoff-${msg.id}`} className="flex items-center gap-3 my-4 text-[11px] font-medium text-zinc-500">
              <span className="flex-1 h-px bg-[#1f1f23]" />
              <span>Continued on {msg.origin} · {formatMsgTime(msg.created_at)}</span>
              <span className="flex-1 h-px bg-[#1f1f23]" />
            </div>
          );
        }
        lastOrigin = msg.origin;
      }
      if (turn && msg.id === turn.botMsgId) {
        items.push(...turnCards);
        cardsPlaced = true;
      }
      items.push(<MessageItem key={msg.client_id || msg.id} message={msg} />);
    }

    if (turn && !cardsPlaced) {
      items.push(...turnCards);
      if (isStreaming && turn.text) {
        items.push(<MessageItem key={turn.botMsgId} message={{ id: turn.botMsgId, sender: 'bot', text: turn.text }} />);
      }
    }
    return items;
  };

  const handleVoiceToggle = () => {
    if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
      alert('Voice recognition is not supported in this browser environment.');
      return;
    }

    if (isListening) {
      setIsListening(false);
    } else {
      try {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        const recognition = new SpeechRecognition();
        recognition.continuous = false;
        recognition.onstart = () => setIsListening(true);
        recognition.onresult = (event) => {
          const transcript = event.results[0][0].transcript;
          setInputPrompt((prev) => prev + (prev ? ' ' : '') + transcript);
          setIsListening(false);
        };
        recognition.onerror = () => setIsListening(false);
        recognition.onend = () => setIsListening(false);
        recognition.start();
      } catch (err) {
        setIsListening(false);
      }
    }
  };

  return (
    <div className="flex-1 flex flex-col h-screen overflow-hidden bg-[#09090b] relative select-none font-sans text-zinc-100">
      {/* Top Header Bar */}
      <header className="px-6 py-3.5 flex items-center justify-between z-20 bg-[#09090b]/80 backdrop-blur-md border-b border-[#18181c]">
        {/* Left Side: Bot Indicator */}
        <div className="flex items-center gap-2.5 min-w-0">
          <MascotAvatar type={avatarType} size="sm" />
          <div className="min-w-0">
            <h2 className="font-bold text-sm text-zinc-100 tracking-wide truncate">{thread?.title || botTitle}</h2>
            {(thread?.title || isStreaming) && (
              <p className={`text-[11px] truncate ${needsApproval ? 'text-amber-400' : isStreaming ? 'text-blue-400' : 'text-zinc-500'}`}>
                {needsApproval ? 'Needs your approval' : isStreaming ? 'Replying…' : botTitle}
              </p>
            )}
          </div>
        </div>


        {/* Right Side: Model Picker & Computer Monitor Toggle */}
        <div className="flex items-center gap-3">
          <ModelPicker
            models={models}
            currentModel={activeModel}
            onSelectModel={handleModelChange}
          />

          <button
            suppressHydrationWarning={true}
            onClick={onToggleComputer}
            className="p-1.5 rounded-lg text-zinc-400 hover:text-white hover:bg-[#1f1f23] transition"
            title="Toggle Desktop Screen Preview"
          >
            <FiMonitor className="text-base" />
          </button>
        </div>
      </header>

      {/* Main Canvas Scrollable Chat Thread */}
      <div className="flex-1 overflow-y-auto px-6 py-4 relative">
        <div className="max-w-4xl mx-auto w-full space-y-3 px-12 md:px-20">
          {/* Centered Recorded Timestamp */}
          <div className="text-center my-4">
            <span className="text-[11px] font-medium text-zinc-500 font-sans tracking-wide">
              {formatHeaderDate(activeMessages)}
            </span>
          </div>

          {/* Message Items List */}
          {loading && messages.length === 0 ? null : renderThread()}

          {isStreaming && !turn.text && !needsApproval && (
            <div className="flex justify-start items-center gap-3 my-3 animate-fade-in">
              <MascotAvatar type={avatarType} size="sm" />
              <div className="bg-[#18181b] border border-[#27272a] px-4 py-3 rounded-2xl flex items-center gap-1.5 shadow-sm">
                <span className="w-2 h-2 rounded-full bg-blue-400 animate-bounce" style={{ animationDelay: '-0.32s' }} />
                <span className="w-2 h-2 rounded-full bg-blue-400 animate-bounce" style={{ animationDelay: '-0.16s' }} />
                <span className="w-2 h-2 rounded-full bg-blue-400 animate-bounce" style={{ animationDelay: '0s' }} />
              </div>
            </div>
          )}


          <div ref={messagesEndRef} />
        </div>
      </div>


      {/* Bottom Floating Pill Composer Input */}
      <div className="p-6 flex flex-col items-center z-20 bg-gradient-to-t from-[#09090b] via-[#09090b]/90 to-transparent">
        {/* Hidden Image File Input */}
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          onChange={handleImageSelect}
          className="hidden"
        />

        {/* Selected Image Thumbnail Preview Chip */}
        {selectedImage && (
          <div className="w-full max-w-2xl flex items-center justify-between bg-[#1c1c20] border border-[#2b2b32] px-3 py-1.5 rounded-xl mb-2 text-xs animate-fade-in shadow-md">
            <div className="flex items-center gap-2.5">
              <img
                src={selectedImage.previewUrl}
                alt="Selected Image Preview"
                className="w-9 h-9 rounded-lg object-cover border border-zinc-700 shadow-sm"
              />
              <div className="flex flex-col">
                <span className="text-zinc-200 font-semibold text-[11px] truncate max-w-[180px]">
                  {selectedImage.file.name}
                </span>
                <span className="text-[10px] text-zinc-400">
                  {selectedImage.isUploading
                    ? 'Uploading image...'
                    : selectedImage.error
                    ? `Upload notice: ${selectedImage.error}`
                    : 'Image ready'}
                </span>
              </div>
            </div>

            <button
              suppressHydrationWarning={true}
              type="button"
              onClick={() => setSelectedImage(null)}
              className="text-zinc-400 hover:text-white p-1 rounded-md hover:bg-[#2a2a30] transition"
              title="Remove image"
            >
              <FiX className="text-sm" />
            </button>
          </div>
        )}

        {sendError && (
          <p role="alert" className="w-full max-w-2xl mb-2 px-1 text-[11px] text-rose-400">{sendError}</p>
        )}

        <form
          onSubmit={handleSendMessage}
          className="w-full max-w-2xl dark-pill-input px-4 py-2.5 flex items-center gap-3 bg-[#1c1c20] border border-[#2b2b32] shadow-2xl transition focus-within:border-zinc-500"
        >
          {/* Plus / Image Upload Action Button */}
          <button
            suppressHydrationWarning={true}
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="text-zinc-400 hover:text-white transition p-1 text-base flex-shrink-0"
            title="Upload Image (JPEG, PNG, WEBP, GIF, AVIF)"
          >
            <FiPlus />
          </button>

          {/* Textarea Input */}
          <textarea
            suppressHydrationWarning={true}
            value={inputPrompt}
            onChange={(e) => setInputPrompt(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                e.currentTarget.form?.requestSubmit();
              }
            }}
            rows={1}
            placeholder={`Message ${botTitle}`}
            className="w-full resize-y bg-transparent text-xs text-zinc-100 placeholder-zinc-500 focus:outline-none max-h-40"
          />

          {/* Microphone Dictation Button */}
          <button
            suppressHydrationWarning={true}
            type="button"
            onClick={handleVoiceToggle}
            className={`p-1.5 rounded-full text-base transition flex-shrink-0 ${
              isListening
                ? 'bg-rose-500 text-white animate-pulse'
                : 'text-zinc-400 hover:text-white'
            }`}
            title="Dictate Voice Input"
          >
            {isListening ? <FiMicOff /> : <FiMic />}
          </button>

        </form>
      </div>

    </div>
  );
}
