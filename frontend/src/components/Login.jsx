import { useState } from "react";
import { api, setToken } from "../api.js";

export default function Login({ onAuthed }) {
  const [mode, setMode] = useState("login"); // "login" | "register"
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const fn = mode === "login" ? api.login : api.register;
      const res = await fn(email.trim(), password);
      setToken(res.access_token);
      onAuthed(res.user);
    } catch (err) {
      setError(err.message || "Authentication failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="center">
      <form className="card auth" onSubmit={submit}>
        <h1>CSTT Agent Studio</h1>
        <p className="muted">
          {mode === "login" ? "Sign in to continue" : "Create your account"}
        </p>

        <label>Email</label>
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          autoComplete="email"
          required
        />

        <label>Password</label>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete={mode === "login" ? "current-password" : "new-password"}
          minLength={8}
          required
        />

        {error && <div className="error">{error}</div>}

        <button type="submit" disabled={busy}>
          {busy ? "…" : mode === "login" ? "Sign in" : "Register"}
        </button>

        <div className="switch">
          {mode === "login" ? (
            <span>
              No account?{" "}
              <a onClick={() => setMode("register")}>Register</a>
            </span>
          ) : (
            <span>
              Have an account?{" "}
              <a onClick={() => setMode("login")}>Sign in</a>
            </span>
          )}
        </div>
      </form>
    </div>
  );
}
