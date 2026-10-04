import React, { Suspense, lazy, useCallback } from "react";
import AquaLogoFallback from "../aqua/AquaLogoFallback.jsx";
import ModelErrorBoundary from "../aqua/ModelErrorBoundary.jsx";
import ChatInput from "./ChatInput.jsx";
import Conversation from "./Conversation.jsx";
import MessageBirthLayer from "./MessageBirthLayer.jsx";

const AquaLogo3D = lazy(() => import("../aqua/AquaLogo3D.jsx"));

export default function ChatShell({
  messages,
  pending,
  waiting,
  onSend,
  onRetry,
  birthId,
  onBirthComplete,
  originRef,
  formingIds,
  inputRef,
  draft,
  onDraftChange,
  focusRequest,
  effectKey
}) {
  const active = messages.length > 0;
  const birthMessage = messages.find((message) => message.id === birthId);
  const finishBirth = useCallback(() => {
    if (birthMessage) onBirthComplete(birthMessage.id);
  }, [birthMessage, onBirthComplete]);

  return (
    <main className={`chat-shell${active ? " chat-shell--active" : " chat-shell--landing"}`}>
      <header className={`brand-zone${active ? " brand-zone--compact" : ""}`}>
        <div
          className={`logo-frame${active ? " logo-frame--compact" : ""}`}
        >
          <ModelErrorBoundary fallback={<AquaLogoFallback compact={active} />}>
            <Suspense fallback={<AquaLogoFallback compact={active} />}>
              <AquaLogo3D compact={active} />
            </Suspense>
          </ModelErrorBoundary>
        </div>
      </header>

      {active ? (
        <Conversation
          key={effectKey}
          messages={messages}
          pending={pending}
          waiting={waiting}
          formingIds={formingIds}
          onRetry={onRetry}
        />
      ) : (
        <section className="hero-copy" aria-label="Ask AQUA">
          <h1>Ask your financial data anything.</h1>
        </section>
      )}

      <footer className={`composer-zone${active ? " composer-zone--active" : ""}`}>
        <ChatInput
          onSend={onSend}
          pending={pending}
          waiting={waiting}
          active={active}
          originRef={originRef}
          inputRef={inputRef}
          draft={draft}
          onDraftChange={onDraftChange}
          focusRequest={focusRequest}
          effectKey={effectKey}
          thinkingCancelled={!pending && messages.at(-1)?.response?.status === "error"}
        />
      </footer>

      {birthMessage && (
        <MessageBirthLayer
          key={birthMessage.id}
          message={birthMessage}
          originRef={originRef}
          onComplete={finishBirth}
        />
      )}
    </main>
  );
}
