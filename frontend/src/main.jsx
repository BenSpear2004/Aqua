import React, { useState } from "react";
import { createRoot } from "react-dom/client";

function App() {
  const [prompt, setPrompt] = useState("");
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false);

  async function ask(event) {
    event.preventDefault();
    setBusy(true);
    setAnswer("");

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt })
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(
          typeof data.detail === "string"
            ? data.detail
            : "The request failed."
        );
      }
      setAnswer(data.answer);
    } catch (error) {
      setAnswer(`Error: ${error.message}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main style={{
      maxWidth: 720, margin: "60px auto",
      padding: 24, fontFamily: "system-ui"
    }}>
      <h1>Bank AI</h1>
      <p>React → FastAPI → Ollama</p>
      <form onSubmit={ask}>
        <textarea
          aria-label="Message"
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          placeholder="Ask your local AI a question..."
          rows={5}
          maxLength={10000}
          required
          style={{ width: "100%", boxSizing: "border-box" }}
        />
        <button disabled={busy || !prompt.trim()}>
          {busy ? "Thinking…" : "Send"}
        </button>
      </form>
      <p aria-live="polite" style={{ whiteSpace: "pre-wrap" }}>
        {answer}
      </p>
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);
