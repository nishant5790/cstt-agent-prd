export default function Sidebar({
  user,
  sessions,
  activeSid,
  onSelect,
  onNew,
  onDelete,
  onLogout,
}) {
  return (
    <aside className="sidebar">
      <div className="sidebar-head">
        <strong>Sessions</strong>
        <button className="small" onClick={onNew}>
          + New
        </button>
      </div>

      <div className="session-list">
        {sessions.length === 0 && (
          <div className="muted pad">No sessions yet.</div>
        )}
        {sessions.map((s) => (
          <div
            key={s.sid}
            className={"session-item" + (s.sid === activeSid ? " active" : "")}
            onClick={() => onSelect(s.sid)}
          >
            <div className="session-title">{s.title}</div>
            <div className="session-summary muted ellipsis">{sessionSummary(s)}</div>
            <div className="session-meta">
              {s.built ? (
                <span className="pill ok">built</span>
              ) : s.building ? (
                <span className="pill warn">building</span>
              ) : (
                <span className="pill">draft</span>
              )}
              {s.has_deck && <span className="pill ok">deck</span>}
            </div>
            <button
              className="del"
              title="Delete session"
              onClick={(e) => {
                e.stopPropagation();
                if (confirm("Delete this session and its data?")) onDelete(s.sid);
              }}
            >
              ×
            </button>
          </div>
        ))}
      </div>

      <div className="sidebar-foot">
        <div className="muted small ellipsis" title={user.email}>
          {user.email}
        </div>
        <button className="small" onClick={onLogout}>
          Logout
        </button>
      </div>
    </aside>
  );
}

function sessionSummary(s) {
  if (s.building) return "Building knowledge base…";
  const topics = s.topics || [];
  if (topics.length) {
    const head = topics.slice(0, 2).join(", ");
    return topics.length > 2 ? `${head} +${topics.length - 2} more` : head;
  }
  const docs = (s.sources || []).length;
  if (docs) return `${docs} document${docs > 1 ? "s" : ""}`;
  return "No documents yet";
}
