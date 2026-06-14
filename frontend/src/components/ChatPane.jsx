import { useEffect, useRef, useState, useCallback } from "react";
import { api } from "../api.js";

let _seq = 0;
const uid = () => `m${++_seq}`;

export default function ChatPane({ sid, onChanged }) {
  const [messages, setMessages] = useState([]);
  const [status, setStatus] = useState(null);
  const [plan, setPlan] = useState(null);
  const [questions, setQuestions] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const fileRef = useRef(null);
  const feedRef = useRef(null);
  const eventCountRef = useRef(0);
  const pendingBuildRef = useRef(false);

  const building = !!status?.building;
  const built = !!status?.built;
  const deckReady = !!status?.deck;
  const hasDraft = !!plan && questions.length === 0;

  // --- helpers ----------------------------------------------------------
  const pushMsg = useCallback((role, text, extra = {}) => {
    setMessages((m) => [...m, { id: uid(), role, text, ...extra }]);
  }, []);

  const refreshStatus = useCallback(async () => {
    try {
      const st = await api.status(sid);
      setStatus(st);
      return st;
    } catch (e) {
      setError(e.message);
      return null;
    }
  }, [sid]);

  const syncEvents = useCallback(async () => {
    try {
      const { events } = await api.events(sid);
      if (events.length > eventCountRef.current) {
        const fresh = events.slice(eventCountRef.current);
        eventCountRef.current = events.length;
        setMessages((m) => [
          ...m,
          ...fresh.map((ev) => ({
            id: uid(),
            role: "system",
            text: ev.message,
            stage: ev.stage,
            error: ev.stage === "error",
          })),
        ]);
      }
    } catch {
      /* ignore */
    }
  }, [sid]);

  const announceReady = useCallback(
    (st) => {
      const topics = st.topics || [];
      const lead =
        "I've finished building the knowledge base from your documents" +
        (st.blocks ? ` (${st.blocks} content blocks).` : ".");
      const ask = topics.length
        ? "What kind of training deck would you like? Pick a topic below or describe your own."
        : "What kind of training deck would you like? Describe the topic and audience.";
      pushMsg("assistant", `${lead} ${ask}`, {
        suggestions: topics.map((t) => `Create a training deck about "${t}"`),
      });
    },
    [pushMsg]
  );

  const applyPlanResult = useCallback(
    (res) => {
      if (res.status === "clarifying") {
        const qs = res.questions || [];
        setQuestions(qs);
        setPlan(null);
        pushMsg("assistant", "A few quick questions so I can tailor the deck:", {
          questions: qs,
        });
      } else {
        setQuestions([]);
        setPlan(res.plan || null);
        if (res.plan) {
          pushMsg(
            "assistant",
            res.status === "approved"
              ? `Approved "${res.plan.deck_title}". You can generate the deck now.`
              : `Here's a draft: "${res.plan.deck_title}" (${res.plan.slides.length} slides). Tell me what to change, or approve it.`,
            { outline: res.plan }
          );
        }
      }
      refreshStatus();
    },
    [pushMsg, refreshStatus]
  );

  // --- initial load -----------------------------------------------------
  useEffect(() => {
    let cancelled = false;
    setMessages([]);
    setStatus(null);
    setPlan(null);
    setQuestions([]);
    setError("");
    eventCountRef.current = 0;
    pendingBuildRef.current = false;

    (async () => {
      const st = await refreshStatus();
      if (cancelled) return;
      try {
        const { events } = await api.events(sid);
        if (cancelled) return;
        eventCountRef.current = events.length;
        if (events.length) {
          setMessages(
            events.map((ev) => ({
              id: uid(),
              role: "system",
              text: ev.message,
              stage: ev.stage,
              error: ev.stage === "error",
            }))
          );
        }
      } catch {
        /* ignore */
      }
      // restore plan conversation state, if any
      try {
        const full = await api.getSession(sid);
        if (cancelled) return;
        const p = full.plan;
        if (p) {
          if (p.status === "clarifying" && (p.questions || []).length) {
            setQuestions(p.questions);
            pushMsg("assistant", "A few quick questions so I can tailor the deck:", {
              questions: p.questions,
            });
          } else if (p.plan) {
            setPlan(p.plan);
            pushMsg(
              "assistant",
              `Current draft: "${p.plan.deck_title}" (${p.plan.slides.length} slides).`,
              { outline: p.plan }
            );
          }
        }
      } catch {
        /* no plan yet */
      }
      if (cancelled) return;
      // greet based on state
      if (st && st.building) {
        pendingBuildRef.current = true;
        pushMsg("assistant", "I'm processing your documents…");
      } else if (st && !st.built) {
        pushMsg(
          "assistant",
          "Hi! Attach your training documents and I'll build a knowledge base, then help you craft a deck."
        );
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sid]);

  // --- poll while building ---------------------------------------------
  useEffect(() => {
    if (!building) return;
    let active = true;
    const timer = setInterval(async () => {
      await syncEvents();
      const st = await refreshStatus();
      if (st && !st.building && active) {
        clearInterval(timer);
        await syncEvents();
        onChanged && onChanged();
        if (pendingBuildRef.current) {
          pendingBuildRef.current = false;
          if (st.built) announceReady(st);
          else if (st.error)
            pushMsg("assistant", `Build failed: ${st.error}`, { error: true });
        }
      }
    }, 2000);
    return () => {
      active = false;
      clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [building]);

  // autoscroll
  useEffect(() => {
    if (feedRef.current) feedRef.current.scrollTop = feedRef.current.scrollHeight;
  }, [messages]);

  // --- actions ----------------------------------------------------------
  async function onAttach(e) {
    const files = [...(e.target.files || [])];
    if (fileRef.current) fileRef.current.value = "";
    if (!files.length) return;
    setError("");
    setBusy(true);
    pushMsg(
      "user",
      `Uploaded ${files.length} file(s): ${files.map((f) => f.name).join(", ")}`
    );
    try {
      await api.upload(sid, files);
      // a new upload invalidates the old KB — rebuild automatically
      pendingBuildRef.current = true;
      pushMsg(
        "assistant",
        "Got it — updating the knowledge base with the new material…"
      );
      await api.build(sid);
      await refreshStatus(); // flips building -> starts poll
      onChanged && onChanged();
    } catch (err) {
      setError(err.message);
      pendingBuildRef.current = false;
    } finally {
      setBusy(false);
    }
  }

  async function send() {
    const text = input.trim();
    if (!text || busy) return;

    if (building) {
      pushMsg("user", text);
      setInput("");
      pushMsg("assistant", "Still processing your documents — one moment.");
      return;
    }
    if (!built) {
      pushMsg("user", text);
      setInput("");
      pushMsg(
        "assistant",
        "Please attach your training documents first so I can build the knowledge base."
      );
      return;
    }

    pushMsg("user", text);
    setInput("");
    setBusy(true);
    setError("");
    try {
      let res;
      if (questions.length) {
        res = await api.planAnswer(sid, { response: text });
      } else if (plan) {
        res = await api.planRevise(sid, text);
      } else {
        res = await api.planStart(sid, text);
      }
      applyPlanResult(res);
      onChanged && onChanged();
    } catch (err) {
      setError(err.message);
      pushMsg("assistant", `Sorry, that failed: ${err.message}`, { error: true });
    } finally {
      setBusy(false);
    }
  }

  async function approve() {
    setBusy(true);
    setError("");
    try {
      await api.planApprove(sid);
      // approval immediately produces the deck
      pushMsg("assistant", "Plan approved — generating your deck…");
      await api.generate(sid);
      await refreshStatus();
      onChanged && onChanged();
      pushMsg("assistant", "Your deck is ready to download.", { done: true });
    } catch (err) {
      setError(err.message);
      pushMsg("assistant", `Sorry, that failed: ${err.message}`, { error: true });
    } finally {
      setBusy(false);
    }
  }

  async function download() {
    try {
      const res = await api.download(sid);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "deck.pptx";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err.message);
    }
  }

  function startNewDeck() {
    // drop the current draft locally so the next message starts a fresh plan
    setPlan(null);
    setQuestions([]);
    const topics = status?.topics || [];
    const ask = topics.length
      ? "Sure — what's the next training deck about? Pick a topic or describe your own."
      : "Sure — what's the next training deck about? Describe the topic and audience.";
    pushMsg("assistant", ask, {
      suggestions: topics.map((t) => `Create a training deck about "${t}"`),
    });
  }

  // --- render -----------------------------------------------------------
  return (
    <div className="chat">
      <header className="chat-head">
        <div>
          <h2>{status?.title || "Session"}</h2>
          <div className="chat-sub muted">
            {building ? (
              <span className="pill warn">building…</span>
            ) : built ? (
              <>
                <span className="pill ok">knowledge base ready</span>
                {status.blocks ? ` · ${status.blocks} blocks` : ""}
                {deckReady && <span className="pill ok">deck ready</span>}
              </>
            ) : (
              <span className="pill">no documents yet</span>
            )}
          </div>
        </div>
      </header>

      <div className="feed" ref={feedRef}>
        {messages.map((m) => (
          <Message key={m.id} m={m} onSuggestion={(s) => setInput(s)} />
        ))}
      </div>

      {error && <div className="error bar">{error}</div>}

      {hasDraft && (
        <div className="actions">
          {deckReady ? (
            <>
              <button className="ok" onClick={download}>
                ⬇ Download .pptx
              </button>
              <button onClick={startNewDeck} disabled={busy}>
                + New deck
              </button>
            </>
          ) : (
            <>
              <button className="primary" onClick={approve} disabled={busy}>
                {busy ? "…" : "✓ Approve plan"}
              </button>
              <button onClick={startNewDeck} disabled={busy}>
                + New deck
              </button>
            </>
          )}
        </div>
      )}

      <div className="composer">
        <input ref={fileRef} type="file" multiple hidden onChange={onAttach} />
        <button
          className="attach"
          title="Attach documents"
          onClick={() => fileRef.current?.click()}
          disabled={busy || building}
        >
          📎
        </button>
        <input
          className="msg-input"
          placeholder={
            building
              ? "Processing documents…"
              : !built
              ? "Attach documents to begin…"
              : questions.length
              ? "Type your answer…"
              : plan
              ? "Request a change, or approve above…"
              : "Describe the training deck you want…"
          }
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
        />
        <button className="send" onClick={send} disabled={busy || !input.trim()}>
          {busy ? "…" : "Send"}
        </button>
      </div>
    </div>
  );
}

function Message({ m, onSuggestion }) {
  if (m.role === "system") {
    return (
      <div className={"msg system" + (m.error ? " err" : "")}>
        {m.stage && <span className="stage">{m.stage}</span>} {m.text}
      </div>
    );
  }
  return (
    <div className={"msg " + m.role}>
      <div className={"bubble" + (m.error ? " err" : "")}>
        <div>{m.text}</div>

        {m.suggestions && m.suggestions.length > 0 && (
          <div className="chips">
            {m.suggestions.map((s, i) => (
              <button key={i} className="chip" onClick={() => onSuggestion(s)}>
                {s.replace(/^Create a training deck about "?|"$/g, "") || s}
              </button>
            ))}
          </div>
        )}

        {m.questions && m.questions.length > 0 && (
          <ul className="qlist">
            {m.questions.map((q) => (
              <li key={q.id}>{q.question}</li>
            ))}
          </ul>
        )}

        {m.outline && (
          <ol className="outline">
            {m.outline.slides.map((s, i) => (
              <li key={i}>
                <div className="slide-title">{s.title}</div>
                <ul>
                  {s.bullets.map((b, j) => (
                    <li key={j}>{b}</li>
                  ))}
                </ul>
              </li>
            ))}
          </ol>
        )}
      </div>
    </div>
  );
}
