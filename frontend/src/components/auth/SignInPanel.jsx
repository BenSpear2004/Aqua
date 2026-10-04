import React, { useEffect, useId, useRef, useState } from "react";
import { loadGoogleIdentity } from "../../services/googleIdentity.js";
import "../../styles/auth.css";

export default function SignInPanel({ auth, dedicated = false }) {
  const buttonRef = useRef(null);
  const [googleStatus, setGoogleStatus] = useState("loading");
  const config = auth.config;
  const generatedTitleId = useId();
  const titleId = dedicated ? "signin-heading" : generatedTitleId;
  const Heading = dedicated ? "h1" : "h2";
  const panelClass = `signin-panel${dedicated ? " signin-panel--dedicated" : ""}`;

  useEffect(() => {
    if (auth.status !== "signedout") { setGoogleStatus("loading"); return undefined; }
    if (!config || !buttonRef.current) return undefined;
    let cancelled = false;
    let resizeObserver;
    let resizeFrame;
    let onResize;
    let renderedWidth = 0;
    const container = buttonRef.current;
    setGoogleStatus("loading");
    void loadGoogleIdentity().then((google) => {
      if (cancelled) return;
      google.initialize({ client_id: config.client_id, nonce: config.nonce, auto_select: false, callback: ({ credential }) => void auth.acceptCredential(credential) });
      const renderButton = () => {
        if (cancelled) return;
        const width = Math.max(200, Math.min(320, Math.floor(container.clientWidth || 300)));
        if (width === renderedWidth) return;
        container.replaceChildren();
        google.renderButton(container, { type: "standard", theme: "outline", size: "large", text: "continue_with", shape: "pill", width });
        renderedWidth = width;
        setGoogleStatus("ready");
      };
      renderButton();
      onResize = () => {
        cancelAnimationFrame(resizeFrame);
        resizeFrame = requestAnimationFrame(() => {
          try { renderButton(); } catch { if (!cancelled) setGoogleStatus("unavailable"); }
        });
      };
      if (typeof ResizeObserver !== "undefined") {
        resizeObserver = new ResizeObserver(onResize);
        resizeObserver.observe(container);
      } else {
        window.addEventListener("resize", onResize);
      }
    }).catch(() => { if (!cancelled) setGoogleStatus("unavailable"); });
    return () => {
      cancelled = true;
      resizeObserver?.disconnect();
      cancelAnimationFrame(resizeFrame);
      if (onResize) window.removeEventListener("resize", onResize);
      container.replaceChildren();
    };
  }, [auth.status, auth.acceptCredential, config]);

  if (auth.status === "authenticated" && !auth.canQuery) {
    return (
      <section className={panelClass} aria-labelledby={titleId} data-auth-state="pending-access">
        <Heading id={titleId} tabIndex={dedicated ? -1 : undefined}>Your account is awaiting access</Heading>
        {auth.user?.email && <p className="signin-panel__identity">Signed in as <strong>{auth.user.email}</strong></p>}
        <p role="status">You're signed in. Contact your AQUA administrator to access your data.</p>
        {auth.error && <p className="signin-panel__error" role="alert" data-testid="auth-error">{auth.error}</p>}
        <div className="signin-panel__actions">
          <button className="text-action auth-retry" type="button" onClick={() => void auth.refresh()}>Check access again</button>
          <button className="text-action auth-retry" type="button" onClick={() => void auth.logout()} data-testid="signout-button">Sign out</button>
        </div>
      </section>
    );
  }
  const busy = ["loading", "signingin", "signingout"].includes(auth.status);
  const unavailable = auth.status === "unavailable" || googleStatus === "unavailable";
  return (
    <section className={panelClass} aria-labelledby={titleId} aria-busy={busy} data-auth-state={auth.status}>
      <Heading id={titleId} tabIndex={dedicated ? -1 : undefined}>{busy ? (auth.status === "signingin" ? "Signing you in…" : auth.status === "signingout" ? "Signing you out…" : "Welcome to AQUA") : dedicated ? "Welcome to AQUA" : "Sign in to AQUA"}</Heading>
      <p className={busy ? "signin-panel__busy" : undefined} role="status">{busy && <span className="signin-panel__spinner" aria-hidden="true" />}{busy ? (auth.status === "loading" ? "Checking your sign-in…" : "Please wait a moment.") : "Continue with Google to ask questions about your data."}</p>
      {auth.status === "signedout" && config && (
        <>
          <div className="google-signin-button" ref={buttonRef} hidden={googleStatus === "unavailable"} aria-label="Continue with Google" data-testid="google-signin-button" />
          {googleStatus === "loading" && <p className="signin-panel__status" role="status">Loading Google sign-in…</p>}
        </>
      )}
      {(auth.error || unavailable) && <p className="signin-panel__error" role="alert" data-testid="auth-error">{auth.error || "Google sign-in is temporarily unavailable. Please try again."}</p>}
      {unavailable && <button className="text-action auth-retry" type="button" onClick={() => void auth.refresh()}>Try again</button>}
    </section>
  );
}
