import { API_BASE } from "./state.js";

/* ====================================================================
   API
   ==================================================================== */
export async function api(path, { raw = false, ...options } = {}) {
  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, { headers: { "Content-Type": "application/json" }, ...options });
  } catch (error) {
    if (error && error.name === "AbortError") throw error;
    throw new Error("Could not reach the Trailbit server. Check your connection and reload this page.");
  }
  if (!response.ok) {
    let detail = `The server returned an error (${response.status}).`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail) && body.detail[0]?.msg) detail = body.detail[0].msg;
    } catch { /* keep the generic message */ }
    const error = new Error(detail);
    error.status = response.status;
    throw error;
  }
  let data;
  try {
    data = await response.json();
  } catch {
    // A proxy or error page answered 200 with something that is not JSON.
    throw new Error("Trailbit could not read the server's reply. Try again in a moment.");
  }
  return raw ? { data, headers: response.headers } : data;
}

/** One page of issues. The server needs 2 or more characters for a search, so a single character is not sent. */
export async function fetchIssues({ q = "", sort = "updated", page = 1 } = {}, signal) {
  const query = new URLSearchParams();
  const text = q.trim();
  if (text.length >= 2) query.set("q", text);
  if (sort !== "updated") query.set("sort", sort);
  if (page > 1) query.set("page", String(page));
  const suffix = query.toString();
  const { data, headers } = await api(`/api/issues${suffix ? `?${suffix}` : ""}`, { signal, raw: true });
  return { issues: data, hasMore: headers.get("X-Has-More") === "true" };
}

export const postJson = (path, githubUrl) =>
  api(path, { method: "POST", body: JSON.stringify({ github_url: githubUrl }) });
