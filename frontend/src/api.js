// Tiny fetch-based API client. All calls attach the bearer token (when present)
// and throw an Error with the server's `detail` message on non-2xx responses.

const BASE = import.meta.env.VITE_API_BASE || "";

let _token = localStorage.getItem("token") || "";

export function setToken(t) {
  _token = t || "";
  if (_token) localStorage.setItem("token", _token);
  else localStorage.removeItem("token");
}

export function getToken() {
  return _token;
}

async function request(path, { method = "GET", body, headers = {}, raw = false } = {}) {
  const opts = { method, headers: { ...headers } };
  if (_token) opts.headers.Authorization = `Bearer ${_token}`;
  if (body instanceof FormData) {
    opts.body = body; // browser sets multipart boundary
  } else if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }

  const res = await fetch(`${BASE}${path}`, opts);
  if (raw) {
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    return res; // caller handles blob/stream
  }
  let data = null;
  const text = await res.text();
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!res.ok) {
    const detail = (data && data.detail) || res.statusText || "request failed";
    const err = new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    err.status = res.status;
    throw err;
  }
  return data;
}

export const api = {
  // --- auth ---
  register: (email, password) =>
    request("/api/auth/register", { method: "POST", body: { email, password } }),
  login: (email, password) =>
    request("/api/auth/login", { method: "POST", body: { email, password } }),
  me: () => request("/api/auth/me"),

  // --- sessions ---
  listSessions: () => request("/api/sessions"),
  createSession: (title) =>
    request("/api/sessions", { method: "POST", body: { title } }),
  getSession: (sid) => request(`/api/sessions/${sid}`),
  deleteSession: (sid) => request(`/api/sessions/${sid}`, { method: "DELETE" }),

  // --- knowledge base ---
  status: (sid) => request(`/api/sessions/${sid}/status`),
  events: (sid, since = 0) => request(`/api/sessions/${sid}/events?since=${since}`),
  sources: (sid) => request(`/api/sessions/${sid}/sources`),
  upload: (sid, files) => {
    const fd = new FormData();
    for (const f of files) fd.append("files", f);
    return request(`/api/sessions/${sid}/upload`, { method: "POST", body: fd });
  },
  deleteSource: (sid, name) =>
    request(`/api/sessions/${sid}/sources/${encodeURIComponent(name)}`, { method: "DELETE" }),
  build: (sid) => request(`/api/sessions/${sid}/build`, { method: "POST", body: {} }),
  search: (sid, q, k = 8) =>
    request(`/api/sessions/${sid}/search?q=${encodeURIComponent(q)}&k=${k}`),

  // --- planning ---
  planStart: (sid, requestText, audience) =>
    request(`/api/sessions/${sid}/plan/start`, {
      method: "POST",
      body: { request: requestText, audience: audience || null },
    }),
  planAnswer: (sid, answers) =>
    request(`/api/sessions/${sid}/plan/answer`, { method: "POST", body: { answers } }),
  planRevise: (sid, feedback) =>
    request(`/api/sessions/${sid}/plan/revise`, { method: "POST", body: { feedback } }),
  planApprove: (sid) =>
    request(`/api/sessions/${sid}/plan/approve`, { method: "POST", body: {} }),
  getPlan: (sid) => request(`/api/sessions/${sid}/plan`),

  // --- generation ---
  generate: (sid) => request(`/api/sessions/${sid}/generate`, { method: "POST", body: {} }),
  downloadUrl: (sid) => `${BASE}/api/sessions/${sid}/download`,
  download: (sid) => request(`/api/sessions/${sid}/download`, { raw: true }),
};
