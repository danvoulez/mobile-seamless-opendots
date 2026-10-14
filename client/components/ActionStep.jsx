'use client';

import React, { useState } from 'react';
import { FiShield, FiCheck, FiX, FiMinus, FiHelpCircle } from 'react-icons/fi';
import { stepKind, stepStatus, toolLabel } from '../lib/liveChat';

const ICONS = { ask: FiShield, done: FiCheck, failed: FiX, skipped: FiMinus };
const PILL = 'h-7 px-3.5 rounded-full border text-[11px] font-semibold transition disabled:opacity-50';
const PILL_OFF = 'border-white/[0.07] bg-white/[0.03] hover:bg-white/[0.055] text-zinc-300';
const PILL_ON = 'border-blue-400/40 bg-blue-500/15 text-blue-100';

// A question the assistant asks (OpenCode's question tool): its choices as
// pills, and a line to type something else when allowed. One question with a
// single choice is answered with one tap; otherwise choose, then Answer.
function QuestionForm({ questions, disabled, onAnswer, onSkip }) {
  const [chosen, setChosen] = useState(() => questions.map(() => []));
  const [typed, setTyped] = useState(() => questions.map(() => ''));
  const oneTap = questions.length === 1 && !questions[0].multiple;
  const answers = questions.map((_, i) => [...chosen[i], ...(typed[i].trim() ? [typed[i].trim()] : [])]);
  const ready = answers.every((answer) => answer.length > 0);

  const choose = (index, label) => {
    if (oneTap) {
      onAnswer([[label]]);
      return;
    }
    setChosen((prev) => prev.map((picked, i) => {
      if (i !== index) return picked;
      if (!questions[i].multiple) return [label];
      return picked.includes(label) ? picked.filter((l) => l !== label) : [...picked, label];
    }));
  };

  return (
    <div className="mt-2 mb-1 space-y-3">
      {questions.map((question, index) => (
        <div key={index} className="space-y-1.5">
          {questions.length > 1 && <p className="text-xs text-zinc-200 break-words">{question.question}</p>}
          <div className="flex flex-wrap gap-1.5">
            {question.options.map((option) => (
              <button
                key={option.label}
                type="button"
                disabled={disabled}
                title={option.description || undefined}
                aria-pressed={chosen[index].includes(option.label)}
                onClick={() => choose(index, option.label)}
                className={`${PILL} ${chosen[index].includes(option.label) ? PILL_ON : PILL_OFF}`}
              >
                {option.label}
              </button>
            ))}
          </div>
          {question.custom && (
            <input
              value={typed[index]}
              disabled={disabled}
              onChange={(event) => setTyped((prev) => prev.map((text, i) => (i === index ? event.target.value : text)))}
              onKeyDown={(event) => { if (event.key === 'Enter' && ready) onAnswer(answers); }}
              placeholder="Or type your answer"
              aria-label={`Your answer: ${question.question}`}
              className="w-full max-w-sm bg-white/[0.03] border border-white/[0.07] rounded-lg px-2.5 py-1.5 text-xs text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-blue-500/60"
            />
          )}
        </div>
      ))}
      <div className="flex items-center gap-2">
        <button type="button" disabled={disabled} onClick={onSkip} className={`${PILL} ${PILL_OFF}`}>
          Skip
        </button>
        {(!oneTap || questions[0].custom) && (
          <button
            type="button"
            disabled={disabled || !ready}
            onClick={() => onAnswer(answers)}
            className="h-7 px-3.5 rounded-full bg-blue-600 hover:bg-blue-500 text-white text-[11px] font-semibold transition disabled:opacity-50"
          >
            Answer
          </button>
        )}
      </div>
    </div>
  );
}

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
  const question = approval?.requestType === 'question';
  const Icon = question && kind === 'ask' ? FiHelpCircle : ICONS[kind];

  const answer = async (action, answers) => {
    setIsSubmitting(true);
    setError('');
    try {
      await onRespond(approval.requestId, action, answers);
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
        {kind === 'ask' && question && (
          <>
            <QuestionForm
              questions={approval.questions || []}
              disabled={isSubmitting}
              onAnswer={(answers) => answer('answer', answers)}
              onSkip={() => answer('deny')}
            />
            {error && <p role="alert" className="text-[11px] text-rose-400">{error}</p>}
          </>
        )}
        {kind === 'ask' && !question && (
          <div className="flex items-center gap-2 mt-2 mb-1">
            <button
              type="button"
              disabled={isSubmitting}
              onClick={() => answer('deny')}
              className="h-7 px-3.5 rounded-full border border-white/[0.07] bg-white/[0.03] hover:bg-white/[0.055] text-zinc-300 text-[11px] font-semibold transition disabled:opacity-50"
            >
              Deny
            </button>
            {approval.always?.length > 0 && (
              <button
                type="button"
                disabled={isSubmitting}
                onClick={() => answer('always')}
                title={`Don't ask again in this project, in any chat: ${approval.always.join(', ')}`}
                className="h-7 px-3.5 rounded-full border border-white/[0.07] bg-white/[0.03] hover:bg-white/[0.055] text-zinc-300 text-[11px] font-semibold transition disabled:opacity-50"
              >
                Always
              </button>
            )}
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
        {kind === 'ask' && !question && approval.always?.length > 0 && (
          <p className="text-[11px] text-zinc-500 break-words">Always: allowed from now on in this project, in every chat: {approval.always.join(', ')}</p>
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
