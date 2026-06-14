"""Agent 4 — Conversation Planner. Runs a deck request through a stateful
clarify -> draft -> revise -> approve loop, persisted as a session.

Sessions are small (request + scope + capped turns + the current plan) and live
in the state store, so any replica can resume a conversation. The actual plan is
authored by AnalysisAgent against the RAG index + knowledge graph.
"""

from __future__ import annotations

import time
import uuid

from app.agents.analysis_agent import AnalysisAgent, DeckPlan
from app.agents.kb_loader import load_graph
from app.core import llm
from app.core.logging import get_logger
from app.state import get_state

log = get_logger("planner")

CLARIFYING = "clarifying"
DRAFTED = "drafted"
APPROVED = "approved"

_MAX_TURNS = 20
_MAX_QUESTIONS = 3

class PlannerError(Exception):
    """Raised for invalid session transitions (mapped to HTTP 4xx)."""

class ConversationPlanner:
    def __init__(self):
        self.analysis = AnalysisAgent()

    # --- public API ---
    def start(self,ws:str , request:str, * , sources: list[str]=None,
              audience :str|None=None) -> dict:
        sid = uuid.uuid4().hex
        now = time.time()

        session = {
            "sid": sid, "request": request.strip(),
            "scope": {"sources": sources or []},
            "audience": audience, "answers": {}, "revisions": [],
            "questions": [], "plan": None, "status": CLARIFYING,
            "turns": [{"role": "user", "text": request.strip(), "ts": now}],
            "created": now, "updated": now,
        }

        topics = self._topics(ws)
        questions = self._clarify(request, topics)
        if questions:
            session["questions"] = questions
            self._note(session, "assistant", "clarifying: " +
                       " | ".join(q["question"] for q in questions))
        else:
            self._draft(ws, session)
        self._save(ws, session)
        return self._public(session)


    def answer(self, ws: str, sid: str, answers: dict[str, str]) -> dict:
        session = self._require(ws, sid)
        if session["status"] == APPROVED:
            raise PlannerError("session already approved")
        session["answers"].update({str(k): str(v) for k, v in (answers or {}).items()})
        session["questions"] = []
        self._note(session, "user", "answers: " +
                   "; ".join(f"{k}={v}" for k, v in answers.items()))
        self._draft(ws, session)
        self._save(ws, session)
        return self._public(session)

    def revise(self, ws: str, sid: str, feedback: str) -> dict:
        session = self._require(ws, sid)
        if session["status"] == APPROVED:
            raise PlannerError("session already approved")
        if not session.get("plan"):
            raise PlannerError("nothing to revise yet — draft a plan first")
        session["revisions"].append(feedback.strip())
        self._note(session, "user", f"revise: {feedback.strip()}")
        self._draft(ws, session)
        self._save(ws, session)
        return self._public(session)


    def approve(self, ws: str, sid: str) -> dict:
        session = self._require(ws, sid)
        if not session.get("plan"):
            raise PlannerError("nothing to approve — draft a plan first")
        session["status"] = APPROVED
        self._note(session, "assistant", "plan approved")
        self._persist_plan(ws, session)
        self._save(ws, session)
        return self._public(session)

    def get(self, ws: str, sid: str) -> dict:
        return self._public(self._require(ws, sid))

    # --- internals ---
    def _draft(self, ws: str, session: dict) -> None:
        request = self._effective_request(session)
        plan: DeckPlan = self.analysis.build_plan(
            ws, request, scope=session["scope"], audience=session.get("audience"))
        session["plan"] = plan.model_dump()
        session["status"] = DRAFTED
        self._note(session, "assistant",
                   f"drafted '{plan.deck_title}' ({len(plan.slides)} slides)")

    def _effective_request(self, session: dict) -> str:
        parts = [session["request"]]
        for k, v in session["answers"].items():
            parts.append(f"{k}: {v}")
        for r in session["revisions"]:
            parts.append(f"Revision: {r}")
        return "\n".join(parts)

    def _clarify(self, request: str, topics: list[str]) -> list[dict]:
        data = llm.chat_json(
            system="You triage a training-deck request. If it clearly states a topic "
                   "and audience, set ready=true. Otherwise ask up to 3 short questions. "
                   'Reply JSON: {"ready": bool, "questions": [str]}.',
            user=f"AVAILABLE TOPICS: {', '.join(topics) or '(none)'}\nREQUEST: {request}",
        )
        if data is not None and "ready" in data:
            if data.get("ready"):
                return []
            qs = [str(q) for q in data.get("questions", []) if str(q).strip()]
            return [{"id": f"q{i+1}", "question": q}
                    for i, q in enumerate(qs[:_MAX_QUESTIONS])]
        # offline fallback
        qs: list[str] = []
        if topics and not self._topic_match(request, topics):
            qs.append("Which topic should the deck focus on? Options: "
                      + ", ".join(topics[:6]))
        if not any(a in request.lower()
                   for a in ("beginner", "intermediate", "advanced", "executive")):
            qs.append("Who is the audience (e.g. beginner, intermediate, executive)?")
        return [{"id": f"q{i+1}", "question": q} for i, q in enumerate(qs[:2])]

    @staticmethod
    def _topic_match(request: str, topics: list[str]) -> bool:
        r = request.lower()
        return any(t.lower() in r or
                   any(tok in r for tok in t.lower().split()) for t in topics)

    def _topics(self, ws: str) -> list[str]:
        graph = load_graph(ws)
        if not graph:
            return get_state().get_workspace(ws).get("topics", [])
        return [n.label for n in graph.nodes if n.type == "topic"]

    def _persist_plan(self, ws: str, session: dict) -> None:
        import json
        from app.storage import get_store
        get_store().put_bytes(ws, "outputs", f"plan-{session['sid']}.json",
                              json.dumps(session["plan"]).encode("utf-8"))

    # --- session store helpers ---
    def _require(self, ws: str, sid: str) -> dict:
        session = get_state().load_session(ws, sid)
        if session is None:
            raise PlannerError("session not found")
        return session

    def _save(self, ws: str, session: dict) -> None:
        session["updated"] = time.time()
        session["turns"] = session["turns"][-_MAX_TURNS:]  # cap history
        get_state().save_session(ws, session["sid"], session)


    @staticmethod
    def _note(session: dict, role: str, text: str) -> None:
        session["turns"].append({"role": role, "text": text, "ts": time.time()})

    @staticmethod
    def _public(session: dict) -> dict:
        return {
            "sid": session["sid"], "status": session["status"],
            "request": session["request"], "scope": session["scope"],
            "questions": session.get("questions", []),
            "plan": session.get("plan"),
            "turns": session.get("turns", []),
            "updated": session.get("updated"),
        }