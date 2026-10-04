import React, { useLayoutEffect } from "react";
import WaterSparkles from "../components/aqua/WaterSparkles.jsx";
import "../styles/legal-page.css";

const contact = <a href="mailto:Spear.g.benjamin@gmail.com">Spear.g.benjamin@gmail.com</a>;

function PrivacyPolicy() {
  return <>
    <p>This policy describes how AQUA handles information when you visit aqua-ai.us, sign in, and ask questions about an authorized database. Benjamin is the contact for AQUA at {contact}.</p>
    <h2>Information we process</h2>
    <p>When you sign in with Google, AQUA receives your Google account identifier, email address, verification status, and available profile information such as your name and profile picture. We use this information to establish your session and check access. AQUA does not receive your Google password or request access to your Gmail messages or Google Drive files.</p>
    <p>When you ask a question, AQUA processes the text you submit, relevant database structure and examples, generated SQL, and the results returned by the connected database. Please submit only information you are authorized to use. Hosting and network services may also process technical information such as IP addresses, browser details, request times, and errors.</p>
    <h2>How information is used and shared</h2>
    <p>We process information to sign you in, enforce access permissions, answer your questions, operate the service, and diagnose problems. Google provides sign-in, Cloudflare handles traffic to the site, and the configured database and model services process requests needed to provide answers.</p>
    <p>Questions, database structure, relevant examples, and information about failed queries are sent to the configured AI model server through Ollama. If semantic retrieval is enabled, questions are also sent to Google's embedding service to find relevant context. Contact us before submitting sensitive information if you need to confirm the model server and retrieval configuration.</p>
    <p>These providers handle information under their applicable terms and privacy policies. See <a href="https://policies.google.com/privacy">Google's Privacy Policy</a> and <a href="https://www.cloudflare.com/privacypolicy/">Cloudflare's Privacy Policy</a>.</p>
    <h2>Cookies and storage</h2>
    <p>AQUA uses necessary cookies to protect the sign-in process and keep you signed in. The login challenge expires after 10 minutes. The session cookie normally expires after one hour, although the administrator can configure a duration between five minutes and 24 hours. Signing out clears AQUA's session cookie from your browser.</p>
    <p>The current application does not create a separate account database or save chat history across page reloads. Conversations remain in the active page's memory until they are cleared, the page reloads, or your session changes. Connected databases, infrastructure logs, and external providers have separate storage and retention practices; clearing a session does not delete those records.</p>
    <h2>Your choices and requests</h2>
    <p>You can stop using AQUA, sign out, or clear site cookies in your browser. Contact Benjamin at {contact} to ask about your information, request access, correction or deletion, or raise a privacy concern. We may need to verify your identity and coordinate with the relevant database owner or service provider. Any privacy rights and exceptions depend on applicable law.</p>
    <h2>Changes to this policy</h2>
    <p>We will update this page when our practices change and revise the date above. Contact us if you need clarification before using AQUA.</p>
  </>;
}

function TermsOfService() {
  return <>
    <p>These terms govern your use of AQUA at aqua-ai.us. AQUA helps authorized users ask natural-language questions about connected databases. By using the service, you agree to these terms. If you do not agree, do not use AQUA. For questions, contact Benjamin at {contact}.</p>
    <h2>Accounts and access</h2>
    <p>Sign in using a Google account you control. Signing in does not automatically grant database access; the administrator must approve your account. You may access only data you have permission to use. Keep your account secure and tell us if you suspect unauthorized access.</p>
    <h2>Permitted use</h2>
    <p>Use AQUA lawfully and within the permissions granted by the database owner. Do not attempt to bypass access controls, obtain other users' information, disrupt the service, introduce malicious content, or use the service to change or damage connected databases. You are responsible for having permission to submit your questions and use or share the resulting information.</p>
    <h2>AI-generated queries and results</h2>
    <p>AQUA generates SQL using AI and applies checks intended to allow read-only queries. AI can misunderstand a question, produce incorrect SQL, or return incomplete or misleading results. Review the SQL and verify important results against reliable records before acting on them. AQUA does not provide professional financial, legal, tax, or accounting advice.</p>
    <h2>Your data and third-party services</h2>
    <p>You and the relevant data owners retain your rights in the information you submit and access. You authorize the processing needed to operate the service and answer your requests, as described in our <a href="/privacy">Privacy Policy</a>. Google sign-in, hosting, database, and AI services may have their own terms. Do not submit data if your obligations prohibit the processing described in that policy.</p>
    <h2>Availability and limits</h2>
    <p>AQUA is an evolving service. Features may change, and errors or interruptions may occur. To the extent permitted by applicable law, the service is provided as available without a guarantee of uninterrupted operation, accuracy, or suitability for a particular purpose. Nothing in these terms excludes rights or protections that cannot lawfully be excluded.</p>
    <h2>Suspension and ending use</h2>
    <p>You may stop using AQUA at any time. We may restrict or suspend access to protect users and data, enforce these terms, or comply with legal obligations. A database owner may also withdraw permission to access their data.</p>
    <h2>Changes and contact</h2>
    <p>We may update these terms as the service changes. Updated terms will appear on this page with a revised date. For questions about these terms or the service, email {contact}.</p>
  </>;
}

export default function LegalPage({ kind }) {
  const privacy = kind === "privacy";
  const title = privacy ? "Privacy Policy" : "Terms of Service";
  useLayoutEffect(() => {
    document.title = `${title} | AQUA`;
    document.getElementById("legal-heading")?.focus({ preventScroll: true });
  }, [title]);
  return <main className="legal-page" data-testid="legal-page">
    <div className="ambient-light" aria-hidden="true" />
    <WaterSparkles />
    <article className="legal-page__content">
      <nav className="legal-page__nav" aria-label="AQUA pages">
        <a href="/signin">Back to AQUA</a>
        <a href={privacy ? "/terms" : "/privacy"}>{privacy ? "Terms of Service" : "Privacy Policy"}</a>
      </nav>
      <header>
        <p className="legal-page__brand">AQUA</p>
        <h1 id="legal-heading" tabIndex={-1}>{title}</h1>
        <p className="legal-page__date">Last updated: October 4, 2026</p>
      </header>
      {privacy ? <PrivacyPolicy /> : <TermsOfService />}
    </article>
  </main>;
}
