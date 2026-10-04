import React, { useEffect, useRef } from "react";
import AquaMessage from "./AquaMessage.jsx";
import UserMessage from "./UserMessage.jsx";

export default function Conversation({ messages, pending, waiting, formingIds = [], onRetry }) {
  const scrollerRef = useRef(null);
  const nearBottomRef = useRef(true);

  const updateNearBottom = () => {
    const node = scrollerRef.current;
    if (node) nearBottomRef.current = node.scrollHeight - node.scrollTop - node.clientHeight < 120;
  };

  useEffect(() => {
    const node = scrollerRef.current;
    if (!node || !nearBottomRef.current) return undefined;
    node.scrollTop = node.scrollHeight;
    const observer = new ResizeObserver(() => {
      if (nearBottomRef.current) node.scrollTop = node.scrollHeight;
    });
    observer.observe(node.querySelector(".conversation__messages") || node);
    return () => observer.disconnect();
  }, [messages, pending]);

  return (
    <section className="conversation" aria-label="Conversation">
      <div
        className="conversation__scroll"
        ref={scrollerRef}
        onScroll={updateNearBottom}
        role="log"
        aria-label="AQUA conversation"
        aria-relevant="additions text"
      >
        <div className="conversation__messages">
          {messages.map((message) => message.role === "user"
            ? <UserMessage key={message.id} message={message} hidden={formingIds.includes(message.id)} />
            : <AquaMessage
                key={message.id}
                message={message}
                hidden={formingIds.includes(message.id)}
                onRetry={onRetry}
              />)}
          {pending && (
            <p className="processing-status" role="status" aria-live="polite">
              <span aria-hidden="true" />{waiting ? "AQUA is exploring your numbers" : "AQUA is preparing your answer"}
            </p>
          )}
        </div>
      </div>
    </section>
  );
}
