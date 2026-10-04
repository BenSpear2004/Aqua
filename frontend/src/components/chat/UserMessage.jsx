import React from "react";

export default function UserMessage({ message, hidden = false }) {
  return (
    <article
      className={`message message--user${hidden ? " message--forming" : ""}`}
      data-message-id={message.id}
      aria-hidden={hidden || undefined}
      inert={hidden || undefined}
    >
      <div className="message__bubble message__bubble--user">
        <p>{message.content}</p>
      </div>
    </article>
  );
}
