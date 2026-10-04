import React, { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import ModelSelector from "./ModelSelector.jsx";
import "../../styles/sidebar.css";

function NavIcon({ kind, className = "" }) {
  const paths = {
    plus: <path d="M12 5v14M5 12h14" />,
    folder: <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" />,
    chat: <path d="M5 4h14a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H9l-6 4V6a2 2 0 0 1 2-2Z" />,
    chevron: <path d="m9 5 7 7-7 7" />,
    menu: <><path d="M4 5h16v14H4Z" /><path d="M10 5v14M6.5 9h1M6.5 12h1" /></>,
    close: <path d="m6 6 12 12M18 6 6 18" />,
    question: <><path d="M9.2 8.5a3 3 0 1 1 5.6 1.4c-.9 1.4-2.8 1.4-2.8 3.1" /><path d="M12 17h.01" /></>
  };
  return <svg className={`nav-icon ${className}`} viewBox="0 0 24 24" aria-hidden="true">{paths[kind]}</svg>;
}

function ConversationLink({ conversation, activeConversationId, onSelectConversation, nested = false }) {
  if (!conversation) return null;
  return (
    <button
      type="button"
      className={`sidebar-link${nested ? " sidebar-link--nested" : ""}${conversation.id === activeConversationId ? " sidebar-link--active" : ""}`}
      aria-current={conversation.id === activeConversationId ? "true" : undefined}
      onClick={() => onSelectConversation(conversation.id)}
      title={conversation.title}
    >
      <NavIcon kind="chat" />
      <span>{conversation.title}</span>
      {conversation.request && <span className="sidebar-link__busy" aria-label="Response in progress" />}
    </button>
  );
}

function ProjectFolder({ folder, conversations, activeConversationId, expandedFolderIds, onToggleFolder, onSelectConversation, idPrefix }) {
  const expanded = expandedFolderIds.includes(folder.id);
  const contentId = `${idPrefix}-${folder.id}`;
  return (
    <li className="project-folder">
      <button className="sidebar-folder" type="button" aria-expanded={expanded} aria-controls={contentId} onClick={() => onToggleFolder(folder.id)}>
        <NavIcon kind="chevron" className={expanded ? "nav-icon--expanded" : ""} />
        <NavIcon kind="folder" />
        <span>{folder.title}</span>
      </button>
      <ul id={contentId} className="project-folder__contents" hidden={!expanded}>
        {folder.conversationIds.map((id) => (
          <li key={id}>
            <ConversationLink conversation={conversations.find((conversation) => conversation.id === id)} activeConversationId={activeConversationId} onSelectConversation={onSelectConversation} nested />
          </li>
        ))}
        {folder.children.map((child) => <ProjectFolder key={child.id} folder={child} conversations={conversations} activeConversationId={activeConversationId} expandedFolderIds={expandedFolderIds} onToggleFolder={onToggleFolder} onSelectConversation={onSelectConversation} idPrefix={idPrefix} />)}
      </ul>
    </li>
  );
}

function SidebarContent({ conversations, activeConversationId, projects, faqs, expandedFolderIds, onToggleFolder, onStartConversation, onSelectConversation, onSelectFAQ, models, selectedModelId, onSelectModel, idPrefix }) {
  const recent = conversations.filter((conversation) => conversation.messages.length).sort((a, b) => b.updatedAt - a.updatedAt).slice(0, 6);
  return (
    <>
      <ModelSelector models={models} selectedModelId={selectedModelId} onSelectModel={onSelectModel} />
      <button className="sidebar-ask" type="button" onClick={onStartConversation}>
        <NavIcon kind="plus" />
        <span>Ask a Question</span>
      </button>
      <nav className="sidebar-navigation" aria-label="AQUA conversations">
        <section className="sidebar-section" aria-labelledby={`${idPrefix}-faq-heading`}>
          <h2 id={`${idPrefix}-faq-heading`}>Frequently Asked Questions</h2>
          <ul className="sidebar-list sidebar-faqs">
            {faqs.map((faq) => <li key={faq.id}><button className="sidebar-link sidebar-link--faq" type="button" onClick={() => onSelectFAQ(faq.prompt)}><NavIcon kind="question" /><span>{faq.title}</span></button></li>)}
          </ul>
        </section>
        <section className="sidebar-section" aria-labelledby={`${idPrefix}-projects-heading`}>
          <h2 id={`${idPrefix}-projects-heading`}>Projects</h2>
          <ul className="sidebar-list sidebar-projects">
            {projects.map((folder) => <ProjectFolder key={folder.id} folder={folder} conversations={conversations} activeConversationId={activeConversationId} expandedFolderIds={expandedFolderIds} onToggleFolder={onToggleFolder} onSelectConversation={onSelectConversation} idPrefix={idPrefix} />)}
          </ul>
        </section>
        <section className="sidebar-section" aria-labelledby={`${idPrefix}-recent-heading`}>
          <h2 id={`${idPrefix}-recent-heading`}>Recent Chats</h2>
          <ul className="sidebar-list sidebar-recents">
            {recent.map((conversation) => <li key={conversation.id}><ConversationLink conversation={conversation} activeConversationId={activeConversationId} onSelectConversation={onSelectConversation} /></li>)}
          </ul>
        </section>
      </nav>
      <div className="sidebar-footer"><span className="sidebar-footer__dot" aria-hidden="true" /><span>Mock workspace</span></div>
    </>
  );
}

export default function Sidebar({
  conversations,
  activeConversationId,
  projects,
  faqs,
  expandedFolderIds,
  onToggleFolder,
  onStartConversation,
  onSelectConversation,
  onSelectFAQ,
  onComposerFocus,
  backgroundRef,
  models,
  selectedModelId,
  onSelectModel
}) {
  const [open, setOpen] = useState(false);
  const [mobileLayout, setMobileLayout] = useState(() => window.matchMedia("(max-width: 900px)").matches);
  const id = useId();
  const triggerRef = useRef(null);
  const dialogRef = useRef(null);
  const closeRef = useRef(null);
  const focusAfterClose = useRef("trigger");
  const composerFocus = useRef(onComposerFocus);
  composerFocus.current = onComposerFocus;

  const closeDrawer = (focusComposer = false) => {
    focusAfterClose.current = focusComposer ? "composer" : "trigger";
    setOpen(false);
  };

  useEffect(() => {
    const media = window.matchMedia("(max-width: 900px)");
    const update = () => {
      setMobileLayout(media.matches);
      if (!media.matches) setOpen(false);
    };
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  useEffect(() => {
    if (!open) return undefined;
    const background = backgroundRef?.current;
    const wasInert = background?.inert ?? false;
    if (background) background.inert = true;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const frame = requestAnimationFrame(() => closeRef.current?.focus());
    const focusableElements = () => [...dialogRef.current.querySelectorAll("button:not(:disabled), a[href], input:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex='-1'])")].filter((element) => element.getClientRects().length > 0);
    const handleKey = (event) => {
      if (event.key === "Escape") {
        // The nested selector owns Escape until its menu has been dismissed.
        if (dialogRef.current?.querySelector('[data-model-menu-open="true"]')) return;
        event.preventDefault();
        event.stopPropagation();
        focusAfterClose.current = "trigger";
        setOpen(false);
      } else if (event.key === "Tab") {
        const elements = focusableElements();
        const first = elements[0];
        const last = elements.at(-1);
        if (!elements.length) {
          event.preventDefault();
          dialogRef.current.focus();
        } else if (event.shiftKey && (document.activeElement === first || !dialogRef.current.contains(document.activeElement))) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && (document.activeElement === last || !dialogRef.current.contains(document.activeElement))) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    const handleFocus = (event) => {
      if (!dialogRef.current?.contains(event.target)) closeRef.current?.focus();
    };
    document.addEventListener("keydown", handleKey, true);
    document.addEventListener("focusin", handleFocus, true);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener("keydown", handleKey, true);
      document.removeEventListener("focusin", handleFocus, true);
      if (background) background.inert = wasInert;
      document.body.style.overflow = previousOverflow;
      queueMicrotask(() => {
        if (focusAfterClose.current === "composer") composerFocus.current?.();
        else triggerRef.current?.focus();
      });
    };
  }, [open, backgroundRef]);

  const data = { conversations, activeConversationId, projects, faqs, expandedFolderIds, onToggleFolder, models, selectedModelId, onSelectModel };
  const desktopActions = {
    onStartConversation: () => { onStartConversation(); onComposerFocus?.(); },
    onSelectConversation,
    onSelectFAQ: (prompt) => { onSelectFAQ(prompt); onComposerFocus?.(); }
  };
  const drawerActions = {
    onStartConversation: () => { onStartConversation(); closeDrawer(true); },
    onSelectConversation: (conversationId) => { onSelectConversation(conversationId); closeDrawer(); },
    onSelectFAQ: (prompt) => { onSelectFAQ(prompt); closeDrawer(true); }
  };

  return (
    <>
      {!mobileLayout && <aside className="sidebar-glass sidebar-desktop" aria-label="Workspace navigation">
        <SidebarContent {...data} {...desktopActions} idPrefix={`${id}-desktop`} />
      </aside>}
      <button className="sidebar-trigger" type="button" ref={triggerRef} aria-label="Open workspace navigation" aria-expanded={open} aria-controls={`${id}-drawer`} onClick={() => { focusAfterClose.current = "trigger"; setOpen(true); }}>
        <NavIcon kind="menu" />
      </button>
      {mobileLayout && open && createPortal(
        <div className="sidebar-drawer-layer">
          <div className="sidebar-drawer-scrim" aria-hidden="true" onPointerDown={() => closeDrawer()} />
          <div className="sidebar-glass sidebar-drawer" role="dialog" aria-modal="true" aria-label="Workspace navigation" id={`${id}-drawer`} ref={dialogRef} tabIndex={-1}>
            <button className="sidebar-close" type="button" ref={closeRef} aria-label="Close workspace navigation" onClick={() => closeDrawer()}><NavIcon kind="close" /></button>
            <SidebarContent {...data} {...drawerActions} idPrefix={`${id}-mobile`} />
          </div>
        </div>, document.body
      )}
    </>
  );
}
