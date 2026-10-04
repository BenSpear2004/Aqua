import React, { lazy, Suspense, useCallback, useEffect, useId, useRef, useState } from "react";
import ModelErrorBoundary from "../aqua/ModelErrorBoundary.jsx";
import ThinkingBubbles from "./ThinkingBubbles.jsx";
import "../aqua/model.css";

const Chatbar3D = lazy(() => import("../aqua/Chatbar3D.jsx"));

export default function ChatInput({
  draft = "", onDraftChange, inputRef, focusRequest, onSend, pending, waiting = pending,
  active, originRef, effectKey, thinkingCancelled,
}) {
  const ownInputRef = useRef(null);
  const textareaRef = inputRef ?? ownInputRef;
  const pressureTimer = useRef(null);
  const [focused, setFocused] = useState(false);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  const [layout, setLayout] = useState(null);
  const [pressure, setPressure] = useState(false);
  const [localDraft, setLocalDraft] = useState("");
  const promptId = useId();
  const controlled = Boolean(onDraftChange);
  const value = controlled ? draft : localDraft;
  const setValue = controlled ? onDraftChange : setLocalDraft;
  const canSend = Boolean(value.trim()) && !pending;
  const geometry = ready && !failed ? layout : null;
  const onReady = useCallback(() => setReady(true), []);
  const onFailure = useCallback(() => setFailed(true), []);
  const onLayout = useCallback((next) => setLayout(next), []);

  useEffect(() => {
    if (focusRequest) textareaRef.current?.focus({ preventScroll: true });
  }, [focusRequest, textareaRef]);
  useEffect(() => () => clearTimeout(pressureTimer.current), []);
  useEffect(() => {
    setPressure(false);
    clearTimeout(pressureTimer.current);
  }, [effectKey]);

  const send = (event) => {
    event.preventDefault();
    if (!canSend) return;
    onSend(value.trim());
    setValue("");
    setPressure(true);
    clearTimeout(pressureTimer.current);
    pressureTimer.current = setTimeout(() => setPressure(false), 260);
    textareaRef.current?.focus({ preventScroll: true });
  };

  const handleKeyDown = (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing && event.keyCode !== 229) {
      event.preventDefault();
      event.currentTarget.form.requestSubmit();
    }
  };

  return (
    <div className="composer-anchor">
      <ThinkingBubbles active={waiting} originRef={originRef} effectKey={effectKey} cancelled={thinkingCancelled} />
      <form
        className={`chat-bar-stage${geometry ? " chat-bar-stage--ready" : " chat-bar-stage--fallback"}${focused ? " chat-bar-stage--focused" : ""}${pressure ? " chat-bar-stage--pressure" : ""}`}
        onSubmit={send}
      >
        {!failed && (
          <ModelErrorBoundary onFailure={onFailure}>
            <Suspense fallback={null}>
              <Chatbar3D focused={focused} onLayout={onLayout} onReady={onReady} onFailure={onFailure} />
            </Suspense>
          </ModelErrorBoundary>
        )}
        {!geometry && <div className="chat-bar-fallback" aria-hidden="true" />}
        <span className="composer-surface" style={geometry?.surface} ref={originRef} aria-hidden="true" />
        <label className="sr-only" htmlFor={promptId}>Ask AQUA about your financial data</label>
        <textarea
          id={promptId}
          className="chat-bar-input"
          style={geometry?.prompt}
          ref={textareaRef}
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={handleKeyDown}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          placeholder="Ask AQUA about your financial data..."
          rows={2}
          maxLength={10000}
          spellCheck="true"
          aria-describedby={`${promptId}-hint`}
        />
        <button
          className="send-button send-button--model"
          style={geometry?.button}
          type="submit"
          disabled={!canSend}
          aria-label={pending ? "AQUA is processing your question" : "Send message"}
        >
          {pending ? <span className="send-spinner" aria-hidden="true" /> : (
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M4.5 12h14M12.5 5.5 19 12l-6.5 6.5" />
            </svg>
          )}
        </button>
      </form>
      <p className="composer-hint" id={`${promptId}-hint`}>
        {active ? "Enter to send · Shift + Enter for a new line" : "Enter to ask · Shift + Enter for a new line"}
      </p>
    </div>
  );
}
