import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useReducedMotion } from "./hooks/useReducedMotion.js";
import ChatShell from "./components/chat/ChatShell.jsx";
import Sidebar from "./components/navigation/Sidebar.jsx";
import WaterSparkles from "./components/aqua/WaterSparkles.jsx";
import { useChat } from "./hooks/useChat.js";

export default function App() {
  const chat = useChat();
  const reducedMotion = useReducedMotion();
  const [births, setBirths] = useState([]);
  const [focusRequest, setFocusRequest] = useState(0);
  const originRef = useRef(null);
  const inputRef = useRef(null);
  const backgroundRef = useRef(null);
  const observedResponses = useRef(new Set());
  const previousConversation = useRef(null);

  useLayoutEffect(() => {
    if (previousConversation.current !== chat.activeConversationId) {
      previousConversation.current = chat.activeConversationId;
      observedResponses.current = new Set(chat.messages.filter((m) => m.role === "aqua").map((m) => m.id));
      setBirths([]);
      return;
    }
    for (const message of chat.messages) {
      if (message.role !== "aqua" || observedResponses.current.has(message.id)) continue;
      if (!["streaming", "success"].includes(message.response?.status)) continue;
      observedResponses.current.add(message.id);
      if (!reducedMotion) setBirths((current) => [...current, message.id]);
    }
  }, [chat.activeConversationId, chat.messages, reducedMotion]);
  useEffect(() => { if (reducedMotion) setBirths([]); }, [reducedMotion]);

  const focusComposer = useCallback(() => setFocusRequest((request) => request + 1), []);
  const send = useCallback((prompt) => {
    const id = chat.submit(prompt);
    if (id && !reducedMotion) setBirths((current) => [...current, id]);
    return id;
  }, [chat.submit, reducedMotion]);
  const completeBirth = useCallback((id) => {
    setBirths((current) => current.filter((messageId) => messageId !== id));
  }, []);
  const startConversation = () => { setBirths([]); chat.startConversation(); focusComposer(); };
  const selectConversation = (id) => { setBirths([]); chat.selectConversation(id); };
  const selectFAQ = (prompt) => { chat.setDraft(prompt); focusComposer(); };

  return (
    <div className="app-shell">
      <div className="ambient-light" aria-hidden="true" />
      <WaterSparkles />
      <Sidebar conversations={chat.conversations} activeConversationId={chat.activeConversationId}
        models={chat.models} selectedModelId={chat.selectedModelId} onSelectModel={chat.setModelId}
        projects={chat.projects} faqs={chat.faqs} expandedFolderIds={chat.expandedFolderIds}
        onToggleFolder={chat.toggleFolder} onStartConversation={startConversation}
        onSelectConversation={selectConversation} onSelectFAQ={selectFAQ}
        onComposerFocus={focusComposer} backgroundRef={backgroundRef} />
      <div className="main-panel" ref={backgroundRef}>
        <ChatShell messages={chat.messages} pending={chat.pending}
          waiting={chat.waiting} onSend={send} onRetry={chat.retry} birthId={births[0] || null}
          formingIds={births} onBirthComplete={completeBirth} originRef={originRef} inputRef={inputRef}
          draft={chat.draft} onDraftChange={chat.setDraft} focusRequest={focusRequest}
          effectKey={chat.activeConversationId} />
      </div>
    </div>
  );
}
