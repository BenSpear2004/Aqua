import { useCallback, useEffect, useRef, useState } from "react";
import { FAQS, PROJECTS, createInitialChatState } from "../mocks/navigation.js";
import { AI_MODELS } from "../mocks/aiModels.js";
import { listModels, retryMessage as retryRequest, sendMessage } from "../services/aquaClient.js";
import { DEMO_MODE } from "../services/runtimeConfig.js";

let nextId = 0;
const createId = (kind) => `${kind}-${Date.now()}-${nextId++}`;
const unexpectedResponse = () => ({
  status: "error",
  error: { code: "unexpected", message: "AQUA couldn't complete that request. Please try again.", retryable: true }
});

export function useChat({ demoMode = DEMO_MODE, canQuery = demoMode, csrfToken = "", onAuthFailure } = {}) {
  const [state, setState] = useState(() => createInitialChatState({ demoMode }));
  const access = useRef(null);
  access.current = { demoMode, canQuery, csrfToken, onAuthFailure };
  // The built-in list until the server says which models it can run.
  const [models, setModels] = useState(AI_MODELS);
  const stateRef = useRef(state);
  const requests = useRef(new Map());
  const mounted = useRef(true);

  // The ref also locks a request synchronously before React's next render.
  const update = useCallback((transform) => {
    if (!mounted.current) return;
    const next = transform(stateRef.current);
    stateRef.current = next;
    setState(next);
  }, []);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      for (const request of requests.current.values()) request.controller.abort();
      requests.current.clear();
    };
  }, []);

  // The server lists its default model first; select it unless the current
  // choice is one the server can run.
  useEffect(() => {
    const controller = new AbortController();
    listModels({ signal: controller.signal, demoMode: access.current.demoMode }).then((available) => {
      if (!available.length) return;
      setModels(available);
      update((current) => available.some((model) => model.id === current.selectedModelId)
        ? current
        : { ...current, selectedModelId: available[0].id });
    }).catch(() => {});
    return () => controller.abort();
  }, [update]);

  const runRequest = useCallback(({ conversationId, requestId, modelId, prompt, replyId, userMessageId, retrying }) => {
    const controller = new AbortController();
    requests.current.set(conversationId, { requestId, modelId, replyId, userMessageId, controller });

    const applyResponse = (response, phase) => {
      if (controller.signal.aborted || requests.current.get(conversationId)?.requestId !== requestId) return;
      update((current) => ({
      ...current,
      conversations: current.conversations.map((conversation) => {
        if (conversation.id !== conversationId || conversation.request?.id !== requestId) return conversation;
        const reply = { id: replyId, role: "aqua", response, replyTo: userMessageId, requestId, conversationId, modelId };
        const exists = conversation.messages.some((message) => message.id === replyId);
        return {
          ...conversation,
          updatedAt: Date.now(),
          request: phase === "complete" ? null : { id: requestId, modelId, phase },
          messages: exists
            ? conversation.messages.map((message) => message.id === replyId ? reply : message)
            : [...conversation.messages, reply]
        };
      })
      }));
    };

    void (async () => {
      try {
        const response = await (retrying ? retryRequest : sendMessage)({
          prompt,
          conversationId,
          requestId,
          modelId,
          demoMode: access.current.demoMode,
          csrfToken: access.current.csrfToken,
          signal: controller.signal,
          onFirstContent: (fragment) => applyResponse(fragment, "streaming"),
          onContent: (fragment) => applyResponse(fragment, "streaming")
        });
        applyResponse(response, "complete");
        if (!controller.signal.aborted && mounted.current && ["sign_in_required", "access_denied"].includes(response.error?.code)) access.current.onAuthFailure?.();
      } catch (error) {
        if (error?.name !== "AbortError") applyResponse(unexpectedResponse(), "complete");
      } finally {
        if (requests.current.get(conversationId)?.requestId === requestId) requests.current.delete(conversationId);
      }
    })();
  }, [update]);

  const stop = useCallback(() => {
    const conversationId = stateRef.current.activeConversationId;
    const running = requests.current.get(conversationId);
    if (!running) return;
    running.controller.abort();
    requests.current.delete(conversationId);
    update((current) => ({
      ...current,
      conversations: current.conversations.map((conversation) => {
        if (conversation.id !== conversationId || conversation.request?.id !== running.requestId) return conversation;
        const existing = conversation.messages.find((message) => message.id === running.replyId);
        const reply = {
          id: running.replyId, role: "aqua", replyTo: running.userMessageId,
          requestId: running.requestId, conversationId, modelId: running.modelId,
          response: { ...existing?.response, status: "stopped", message: existing?.response?.message || "", error: null }
        };
        return {
          ...conversation, request: null, updatedAt: Date.now(),
          messages: existing
            ? conversation.messages.map((message) => message.id === reply.id ? reply : message)
            : [...conversation.messages, reply]
        };
      })
    }));
  }, [update]);

  const submit = useCallback((rawPrompt) => {
    const prompt = rawPrompt.trim();
    const current = stateRef.current;
    const conversation = current.conversations.find((item) => item.id === current.activeConversationId);
    if (!access.current.canQuery || !prompt || !conversation || conversation.request) return null;
    const requestId = createId("request");
    const userMessageId = createId("message");
    const replyId = createId("message");
    const modelId = current.selectedModelId;
    update((snapshot) => ({
      ...snapshot,
      conversations: snapshot.conversations.map((item) => item.id === conversation.id ? {
        ...item,
        draft: "",
        title: item.messages.length ? item.title : prompt.replace(/\s+/g, " ").slice(0, 44),
        updatedAt: Date.now(),
        request: { id: requestId, modelId, phase: "waiting" },
        messages: [...item.messages, { id: userMessageId, role: "user", content: prompt, requestId, conversationId: item.id, modelId }]
      } : item)
    }));
    runRequest({ conversationId: conversation.id, requestId, modelId, prompt, replyId, userMessageId, retrying: false });
    return userMessageId;
  }, [runRequest, update]);

  const retry = useCallback((messageId) => {
    const current = stateRef.current;
    const conversation = current.conversations.find((item) => item.id === current.activeConversationId);
    if (!access.current.canQuery || !conversation || conversation.request) return;
    const reply = conversation.messages.find((message) => message.id === messageId);
    const prompt = conversation.messages.find((message) => message.id === reply?.replyTo)?.content;
    if (!prompt || reply?.response?.status !== "error" || !reply.response.error?.retryable) return;
    const requestId = createId("request");
    const modelId = reply.modelId ?? current.selectedModelId;
    update((snapshot) => ({
      ...snapshot,
      conversations: snapshot.conversations.map((item) => item.id === conversation.id ? {
        ...item,
        request: { id: requestId, modelId, phase: "waiting" },
        messages: item.messages.map((message) => message.id === messageId
          ? { ...message, requestId, response: { status: "loading" } }
          : message)
      } : item)
    }));
    runRequest({ conversationId: conversation.id, requestId, modelId, prompt, replyId: messageId, userMessageId: reply.replyTo, retrying: true });
  }, [runRequest, update]);

  const startConversation = useCallback(() => {
    const id = createId("conversation");
    update((current) => ({
      ...current,
      activeConversationId: id,
      conversations: [{ id, title: "Ask a Question", messages: [], draft: "", updatedAt: Date.now(), request: null }, ...current.conversations]
    }));
    return id;
  }, [update]);

  const selectConversation = useCallback((id) => {
    update((current) => current.conversations.some((conversation) => conversation.id === id)
      ? { ...current, activeConversationId: id }
      : current);
  }, [update]);

  const setDraft = useCallback((draft) => {
    update((current) => ({
      ...current,
      conversations: current.conversations.map((conversation) => conversation.id === current.activeConversationId
        ? { ...conversation, draft: String(draft).slice(0, access.current.demoMode ? 10000 : 2000) }
        : conversation)
    }));
  }, [update]);

  const setModelId = useCallback((modelId) => {
    if (!models.some((model) => model.id === modelId)) return;
    update((current) => current.selectedModelId === modelId ? current : { ...current, selectedModelId: modelId });
  }, [models, update]);

  const toggleFolder = useCallback((id) => {
    update((current) => ({
      ...current,
      expandedFolderIds: current.expandedFolderIds.includes(id)
        ? current.expandedFolderIds.filter((folderId) => folderId !== id)
        : [...current.expandedFolderIds, id]
    }));
  }, [update]);

  const active = state.conversations.find((conversation) => conversation.id === state.activeConversationId);
  return {
    messages: active.messages,
    pending: Boolean(active.request),
    waiting: active.request?.phase === "waiting",
    submit,
    stop,
    retry,
    conversations: state.conversations,
    activeConversationId: state.activeConversationId,
    models,
    selectedModelId: state.selectedModelId,
    setModelId,
    projects: demoMode ? PROJECTS : [],
    faqs: FAQS,
    expandedFolderIds: state.expandedFolderIds,
    toggleFolder,
    startConversation,
    selectConversation,
    draft: active.draft,
    setDraft
  };
}
