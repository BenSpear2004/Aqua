import React, { lazy, Suspense, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import FinancialTable from "../data/FinancialTable.jsx";

const DashboardPreview = lazy(() => import("../data/DashboardPreview.jsx"));

// Every answer shows the exact SQL behind it; a refused query shows the SQL
// that was blocked, so the user can see why.
function SqlBlock({ sql, label = "SQL" }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef(null);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  if (!sql) return null;

  const copySql = async () => {
    try {
      await navigator.clipboard.writeText(sql);
      setCopied(true);
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setCopied(false), 1800);
    } catch {
      setCopied(false);
    }
  };

  return (
    <details className="sql-block">
      <summary>{label}</summary>
      <pre><code>{sql}</code></pre>
      <button type="button" className="text-action" onClick={copySql}>{copied ? "Copied" : "Copy SQL"}</button>
    </details>
  );
}

export default function AquaMessage({ message, hidden = false, onRetry }) {
  const [copyStatus, setCopyStatus] = useState("");
  const copyTimer = useRef(null);
  useEffect(() => () => window.clearTimeout(copyTimer.current), []);
  const response = message.response || {};

  const copyResponse = async () => {
    try {
      await navigator.clipboard.writeText(response.message || "");
      setCopyStatus("Response copied");
      window.clearTimeout(copyTimer.current);
      copyTimer.current = window.setTimeout(() => setCopyStatus(""), 1800);
    } catch {
      setCopyStatus("Copy unavailable in this browser");
    }
  };

  if (response.status === "loading") {
    return (
      <article className={`message message--aqua${hidden ? " message--forming" : ""}`} data-message-id={message.id} aria-hidden={hidden || undefined} inert={hidden || undefined}>
        <div className="message__bubble message__bubble--aqua aqua-loading">
          <span className="status-mark" aria-hidden="true">AQUA</span>
          <span>AQUA is thinking…</span>
        </div>
      </article>
    );
  }

  if (response.status === "error") {
    return (
      <article className={`message message--aqua${hidden ? " message--forming" : ""}`} data-message-id={message.id} aria-hidden={hidden || undefined} inert={hidden || undefined}>
        <div className="message__bubble message__bubble--aqua error-card">
          <span className="status-mark" aria-hidden="true">AQUA</span>
          <p>{response.error?.message || "AQUA couldn't complete that request. Please try again."}</p>
          <SqlBlock sql={response.sql} label="SQL that was not run" />
          {response.error?.retryable && (
            <button type="button" className="text-action" onClick={() => onRetry(message.id)}>
              Try again
            </button>
          )}
        </div>
      </article>
    );
  }

  return (
    <article className={`message message--aqua${hidden ? " message--forming" : ""}`} data-message-id={message.id} aria-hidden={hidden || undefined} inert={hidden || undefined}>
      <div className="message__bubble message__bubble--aqua">
        <span className="status-mark" aria-label="AQUA response">AQUA</span>
        <div className="markdown-response">
          <ReactMarkdown>{response.message || ""}</ReactMarkdown>
          {response.status === "stopped" && <p role="status">Response stopped.</p>}
        </div>
        <SqlBlock sql={response.sql} />
        {(response.tables?.length > 0 || response.visualizations?.length > 0 || response.kpis?.length > 0) && (
          <div className="response-data">
            {response.tables?.map((table) => <FinancialTable key={table.id} table={table} />)}
            {(response.visualizations?.length > 0 || response.kpis?.length > 0) && (
              <Suspense fallback={<p className="chart-loading">Preparing dashboard preview…</p>}>
                <DashboardPreview
                  visualizations={response.visualizations}
                  tables={response.tables}
                  kpis={response.kpis}
                />
              </Suspense>
            )}
          </div>
        )}
        {(response.status !== "stopped" || response.message) && <div className="response-actions">
          <button type="button" className="text-action" onClick={copyResponse}>
            {copyStatus === "Response copied" ? "Copied" : "Copy response"}
          </button>
          <span className="action-feedback" role="status" aria-live="polite">{copyStatus}</span>
          {response.model && <span className="answered-by">Answered by {response.model}</span>}
        </div>}
      </div>
    </article>
  );
}
