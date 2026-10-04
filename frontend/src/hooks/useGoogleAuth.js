import { useCallback, useEffect, useRef, useState } from "react";
import { AuthError, fetchAuthConfig, fetchSession, signInWithGoogle, signOut } from "../services/authClient.js";
import { disableGoogleAutoSelect } from "../services/googleIdentity.js";
import { DEMO_MODE } from "../services/runtimeConfig.js";

const initialState = { status: "loading", session: null, config: null, error: "" };

export function useGoogleAuth({ demoMode = DEMO_MODE } = {}) {
  const [state, setState] = useState(() => demoMode ? { ...initialState, status: "demo" } : initialState);
  const stateRef = useRef(state);
  const active = useRef(null);
  const mounted = useRef(false);
  const replace = useCallback((next) => {
    if (!mounted.current) return;
    stateRef.current = next;
    setState(next);
  }, []);
  const begin = useCallback(() => {
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    return controller;
  }, []);
  const isCurrent = (controller) => mounted.current && active.current === controller && !controller.signal.aborted;

  const refresh = useCallback(async () => {
    if (demoMode) return;
    const controller = begin();
    replace(initialState);
    try {
      const session = await fetchSession({ signal: controller.signal });
      const config = session ? null : await fetchAuthConfig({ signal: controller.signal });
      if (isCurrent(controller)) replace({ status: session ? "authenticated" : "signedout", session, config, error: "" });
    } catch (error) {
      if (isCurrent(controller)) replace({ ...initialState, status: "unavailable", error: error.message });
    }
  }, [begin, demoMode, replace]);

  useEffect(() => {
    mounted.current = true;
    if (!demoMode) void refresh();
    return () => { mounted.current = false; active.current?.abort(); };
  }, [demoMode, refresh]);

  const acceptCredential = useCallback(async (credential) => {
    const current = stateRef.current;
    if (demoMode || current.status !== "signedout" || !current.config) return;
    const controller = begin();
    replace({ ...current, status: "signingin", error: "" });
    try {
      const session = await signInWithGoogle({ credential, csrfToken: current.config.csrf_token, signal: controller.signal });
      if (isCurrent(controller)) replace({ status: "authenticated", session, config: null, error: "" });
    } catch (error) {
      if (!isCurrent(controller)) return;
      try {
        const config = await fetchAuthConfig({ signal: controller.signal });
        if (isCurrent(controller)) replace({ ...initialState, status: "signedout", config, error: error.message });
      } catch (configError) {
        if (isCurrent(controller)) replace({ ...initialState, status: "unavailable", error: configError.message });
      }
    }
  }, [begin, demoMode, replace]);

  const logout = useCallback(async () => {
    const current = stateRef.current;
    if (demoMode || current.status !== "authenticated") return;
    const controller = begin();
    replace({ ...current, status: "signingout", error: "" });
    try {
      await signOut({ csrfToken: current.session.csrf_token, signal: controller.signal });
    } catch (error) {
      if (!isCurrent(controller)) return;
      if (!(error instanceof AuthError && error.status === 401)) {
        replace({ ...current, error: "AQUA couldn't sign you out. Please try again." });
        return;
      }
    }
    if (!isCurrent(controller)) return;
    disableGoogleAutoSelect();
    replace({ ...initialState, status: "signedout" });
    try {
      const config = await fetchAuthConfig({ signal: controller.signal });
      if (isCurrent(controller)) replace({ ...initialState, status: "signedout", config });
    } catch (error) {
      if (isCurrent(controller)) replace({ ...initialState, status: "unavailable", error: error.message });
    }
  }, [begin, demoMode, replace]);

  return {
    ...state, demoMode, refresh, logout, acceptCredential,
    user: state.session?.user ?? null,
    csrfToken: state.session?.csrf_token ?? "",
    canQuery: demoMode || (state.status === "authenticated" && state.session?.can_query === true)
  };
}
