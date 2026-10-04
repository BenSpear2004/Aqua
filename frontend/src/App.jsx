import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useReducedMotion } from "./hooks/useReducedMotion.js";
import ChatShell from "./components/chat/ChatShell.jsx";
import Sidebar from "./components/navigation/Sidebar.jsx";
import WaterSparkles from "./components/aqua/WaterSparkles.jsx";
import { useChat } from "./hooks/useChat.js";
import { useGoogleAuth } from "./hooks/useGoogleAuth.js";
import SignInPage from "./pages/SignInPage.jsx";
import LegalPage from "./pages/LegalPage.jsx";

export default function App() {
  const [path, setPath] = useState(() => window.location.pathname);
  useEffect(() => {
    const syncPath = () => setPath(window.location.pathname);
    window.addEventListener("popstate", syncPath);
    return () => window.removeEventListener("popstate", syncPath);
  }, []);
  // Public policy pages must remain readable even when authentication is down.
  if (path === "/privacy" || path === "/terms") return <LegalPage kind={path.slice(1)} />;
  return <AuthenticatedApp />;
}

function AuthenticatedApp() {
  const auth = useGoogleAuth();
  const showWorkspace = auth.demoMode || (auth.status === "authenticated" && auth.canQuery);

  useLayoutEffect(() => {
    const path = showWorkspace ? "/" : "/signin";
    const syncPath = () => {
      if (["/privacy", "/terms"].includes(window.location.pathname)) return;
      if (window.location.pathname !== path || window.location.search || window.location.hash) {
        window.history.replaceState(window.history.state, "", path);
      }
    };
    syncPath();
    document.title = showWorkspace ? "AQUA | Your data, clearly" : "Sign in | AQUA";
    document.getElementById(showWorkspace ? "workspace-heading" : "signin-heading")?.focus({ preventScroll: true });
    window.addEventListener("popstate", syncPath);
    return () => window.removeEventListener("popstate", syncPath);
  }, [showWorkspace]);

  // A session/account transition remounts only private workspace state. Cleanup
  // aborts every outstanding query before another identity can receive results.
  const sessionKey = auth.demoMode ? "demo" : auth.status === "authenticated" ? auth.user.sub : "signedout";
  return showWorkspace ? <Workspace key={sessionKey} auth={auth} /> : <SignInPage auth={auth} />;
}

function Workspace({ auth }) {
  const chat = useChat({ demoMode: auth.demoMode, canQuery: auth.canQuery, csrfToken: auth.csrfToken, onAuthFailure: auth.refresh });
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
        onComposerFocus={focusComposer} backgroundRef={backgroundRef} auth={auth} />
      <div className="main-panel" ref={backgroundRef}>
        {auth.demoMode && <span className="workspace-mode">Demo · fictional sample data</span>}
        <ChatShell messages={chat.messages} pending={chat.pending}
          waiting={chat.waiting} onSend={send} onRetry={chat.retry} birthId={births[0] || null}
          formingIds={births} onBirthComplete={completeBirth} originRef={originRef} inputRef={inputRef}
          draft={chat.draft} onDraftChange={chat.setDraft} focusRequest={focusRequest}
          effectKey={chat.activeConversationId} disabled={!auth.canQuery}
          maxQuestionLength={auth.demoMode ? 10000 : 2000}
          disabledHint="Sign in to ask a question." />
      </div>
    </div>
  );
}
