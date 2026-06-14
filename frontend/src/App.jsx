import { useEffect, useState, useCallback } from "react";
import { api, getToken, setToken } from "./api.js";
import Login from "./components/Login.jsx";
import Sidebar from "./components/Sidebar.jsx";
import ChatPane from "./components/ChatPane.jsx";

export default function App() {
  const [user, setUser] = useState(null);
  const [booting, setBooting] = useState(true);
  const [sessions, setSessions] = useState([]);
  const [activeSid, setActiveSid] = useState(null);

  // resume an existing token on load
  useEffect(() => {
    if (!getToken()) {
      setBooting(false);
      return;
    }
    api
      .me()
      .then(setUser)
      .catch(() => setToken(""))
      .finally(() => setBooting(false));
  }, []);

  const refreshSessions = useCallback(async () => {
    if (!getToken()) return;
    try {
      const { sessions } = await api.listSessions();
      setSessions(sessions);
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    if (user) refreshSessions();
  }, [user, refreshSessions]);

  function onAuthed(authUser) {
    setUser(authUser);
  }

  function logout() {
    setToken("");
    setUser(null);
    setSessions([]);
    setActiveSid(null);
  }

  async function newSession() {
    // name sequentially as "Session N", surviving deletes
    let maxN = 0;
    for (const s of sessions) {
      const m = /^Session (\d+)/.exec(s.title || "");
      if (m) maxN = Math.max(maxN, parseInt(m[1], 10));
    }
    const s = await api.createSession(`Session ${maxN + 1}`);
    await refreshSessions();
    setActiveSid(s.sid);
  }

  async function removeSession(sid) {
    await api.deleteSession(sid);
    if (activeSid === sid) setActiveSid(null);
    await refreshSessions();
  }

  if (booting) return <div className="center muted">Loading…</div>;
  if (!user) return <Login onAuthed={onAuthed} />;

  return (
    <div className="app">
      <Sidebar
        user={user}
        sessions={sessions}
        activeSid={activeSid}
        onSelect={setActiveSid}
        onNew={newSession}
        onDelete={removeSession}
        onLogout={logout}
      />
      <main className="main">
        {activeSid ? (
          <ChatPane
            key={activeSid}
            sid={activeSid}
            onChanged={refreshSessions}
          />
        ) : (
          <div className="center muted">
            <div>
              <h2>Welcome, {user.email}</h2>
              <p>Select a session or create a new one to begin.</p>
              <button onClick={newSession}>+ New session</button>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
