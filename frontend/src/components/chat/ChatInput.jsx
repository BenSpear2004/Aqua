import React, { lazy, Suspense, useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import ModelErrorBoundary from "../aqua/ModelErrorBoundary.jsx";
import ThinkingBubbles from "./ThinkingBubbles.jsx";
import "../aqua/model.css";

const Chatbar3D = lazy(() => import("../aqua/Chatbar3D.jsx"));

export default function ChatInput({
  draft = "", onDraftChange, inputRef, focusRequest, onSend, onStop, pending, waiting = pending,
  active, originRef, effectKey, thinkingCancelled, disabled = false, disabledHint, maxQuestionLength = 10000,
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
  const [desktop, setDesktop] = useState(() => window.matchMedia("(min-width: 901px)").matches);
  const promptId = useId();
  const controlled = Boolean(onDraftChange);
  const value = controlled ? draft : localDraft;
  const setValue = controlled ? onDraftChange : setLocalDraft;
  const canSend = Boolean(value.trim()) && !pending && !disabled;
  const geometry = ready && !failed ? layout : null;
  const onReady = useCallback(() => setReady(true), []);
  const onFailure = useCallback(() => setFailed(true), []);
  const onLayout = useCallback((next) => setLayout(next), []);

  useEffect(() => {
    const media = window.matchMedia("(min-width: 901px)");
    const update = () => setDesktop(media.matches);
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  useLayoutEffect(() => {
    const input = textareaRef.current;
    if (!input) return;
    if (!desktop) {
      input.style.paddingBlock = "";
      return;
    }
    // Measure real wrapped lines so a short draft and a two-line draft both sit
    // in the middle, while longer drafts keep the existing scrolling behavior.
    const height = input.clientHeight;
    const previousHeight = input.style.height;
    const previousMinimum = input.style.minHeight;
    const previousScroll = input.scrollTop;
    input.style.minHeight = "0px";
    input.style.height = "0px";
    input.style.paddingBlock = "0px";
    const contentHeight = input.scrollHeight;
    input.style.height = previousHeight;
    input.style.minHeight = previousMinimum;
    input.style.paddingBlock = `${Math.max(0, (height - Math.min(contentHeight, height)) / 2)}px`;
    input.scrollTop = previousScroll;
  }, [desktop, value, geometry, textareaRef]);

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
    if (onSend(value.trim()) === null) return;
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
              <Chatbar3D desktop={desktop} focused={focused} onLayout={onLayout} onReady={onReady} onFailure={onFailure} />
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
          maxLength={maxQuestionLength}
          disabled={disabled}
          spellCheck="true"
          aria-describedby={`${promptId}-hint`}
        />
        <button
          className="send-button send-button--model"
          style={geometry?.button}
          type={pending ? "button" : "submit"}
          onClick={pending ? onStop : undefined}
          disabled={pending ? disabled || !onStop : !canSend}
          aria-label={pending ? "Stop response" : "Send message"}
          title={pending ? "Stop response" : "Send message"}
        >
          {pending ? <span className="send-stop-icon" aria-hidden="true" /> : (
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M4.5 12h14M12.5 5.5 19 12l-6.5 6.5" />
            </svg>
          )}
        </button>
      </form>
      <p className="composer-hint" id={`${promptId}-hint`}>
        {disabled ? disabledHint : active ? "Enter to send · Shift + Enter for a new line" : "Enter to ask · Shift + Enter for a new line"}
      </p>
    </div>
  );
}
