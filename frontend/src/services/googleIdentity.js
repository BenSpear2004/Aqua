let loading;

export function loadGoogleIdentity() {
  if (globalThis.google?.accounts?.id) return Promise.resolve(globalThis.google.accounts.id);
  if (loading) return loading;
  loading = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.id = "aqua-google-identity";
    const finish = (error) => {
      clearTimeout(timer);
      script.onload = null;
      script.onerror = null;
      if (error) { script.remove(); reject(error); }
      else resolve(globalThis.google.accounts.id);
    };
    const timer = setTimeout(() => finish(new Error("Google sign-in is unavailable.")), 15000);
    script.onload = () => finish(globalThis.google?.accounts?.id ? null : new Error("Google sign-in is unavailable."));
    script.onerror = () => finish(new Error("Google sign-in is unavailable."));
    document.head.appendChild(script);
  }).catch((error) => { loading = undefined; throw error; });
  return loading;
}

export function disableGoogleAutoSelect() {
  globalThis.google?.accounts?.id?.disableAutoSelect();
}
