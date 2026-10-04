import React from "react";

export default function AccountProfile({ auth }) {
  if (auth.demoMode) return <div className="sidebar-footer"><span className="sidebar-footer__dot" aria-hidden="true" /><span>Demo · fictional sample data</span></div>;
  if (!auth.user) return <div className="sidebar-footer"><span className="sidebar-footer__dot" aria-hidden="true" /><span>Sign in to AQUA</span></div>;
  return (
    <div className="account-profile" data-testid="account-profile">
      <div className="account-profile__identity">
        <span className="account-profile__avatar" aria-hidden="true">{(auth.user.name || auth.user.email).slice(0, 1).toUpperCase()}</span>
        <div><strong>{auth.user.name || "Google account"}</strong><span>{auth.user.email}</span></div>
      </div>
      {auth.error && <p className="account-profile__error" role="alert">{auth.error}</p>}
      <button className="text-action" type="button" disabled={auth.status !== "authenticated"} onClick={() => void auth.logout()} data-testid="signout-button">{auth.status === "signingout" ? "Signing out…" : "Sign out"}</button>
    </div>
  );
}
