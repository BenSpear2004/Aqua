import React, { lazy, Suspense } from "react";
import AquaLogoFallback from "../components/aqua/AquaLogoFallback.jsx";
import ModelErrorBoundary from "../components/aqua/ModelErrorBoundary.jsx";
import WaterSparkles from "../components/aqua/WaterSparkles.jsx";
import SignInPanel from "../components/auth/SignInPanel.jsx";
import "../styles/signin-page.css";

const AquaLogo3D = lazy(() => import("../components/aqua/AquaLogo3D.jsx"));

export default function SignInPage({ auth }) {
  return (
    <main className="signin-page" aria-label="AQUA sign-in" data-testid="signin-page">
      <div className="ambient-light" aria-hidden="true" />
      <WaterSparkles />
      <div className="signin-page__panel">
        <header className="signin-page__brand">
          <div className="logo-frame signin-page__logo" aria-hidden="true">
            <ModelErrorBoundary fallback={<AquaLogoFallback />}>
              <Suspense fallback={<AquaLogoFallback />}>
                <AquaLogo3D />
              </Suspense>
            </ModelErrorBoundary>
          </div>
        </header>
        <SignInPanel auth={auth} dedicated />
        <footer className="signin-page__footer">
          <p>Google handles sign-in.<br />AQUA never receives your Google password.</p>
          <nav aria-label="Policies">
            <a href="/privacy">Privacy Policy</a>
            <a href="/terms">Terms of Service</a>
          </nav>
        </footer>
      </div>
    </main>
  );
}
