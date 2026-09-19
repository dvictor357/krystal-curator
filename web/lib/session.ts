/** Cheap client-side signal that a session cookie probably exists (set/cleared by the backend). */
export function signedInHint() {
  try {
    return document.cookie.split("; ").includes("curator_signed_in=1");
  } catch {
    return false;
  }
}
export function clearSignedInHint() {
  document.cookie = "curator_signed_in=; Max-Age=0; path=/";
}
/** Verify the hint against the backend; false on 401 (and drops the stale hint). */
export async function hasSession() {
  if (!signedInHint()) return false;
  try {
    const r = await fetch("/api/account", { credentials: "same-origin" });
    if (r.ok) return true;
    if (r.status === 401) clearSignedInHint();
    return false;
  } catch {
    return false;
  }
}
