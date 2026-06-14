"""End-to-end smoke run against the real API + real Azure LLM (per-session model).

Exercises the full authenticated flow through HTTP: register -> create session
-> upload -> build -> events -> sources -> search -> plan(start/answer/revise/
approve) -> generate -> download -> delete. Run from the backend dir:

    .\\.venv\\Scripts\\python.exe tests\\e2e_run.py
"""
from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))  # allow `import app.*` when run from tests/

from fastapi.testclient import TestClient

from app.main import app

XLSX = BACKEND / "data" / "inputs" / "qtest-Test steps.xlsx"


def banner(step: str) -> None:
    print("\n" + "=" * 70 + f"\n  {step}\n" + "=" * 70)


def main() -> None:
    assert XLSX.exists(), f"missing sample file: {XLSX}"
    client = TestClient(app)

    banner("1. HEALTH")
    print(client.get("/health").json())

    banner("2. REGISTER + LOGIN")
    email = f"e2e-{uuid.uuid4().hex[:8]}@example.com"
    reg = client.post("/api/auth/register",
                      json={"email": email, "password": "secret12"})
    print("register:", reg.status_code, reg.json()["user"]["email"])
    token = reg.json()["access_token"]
    H = {"Authorization": f"Bearer {token}"}

    banner("3. CREATE SESSION")
    sid = client.post("/api/sessions", headers=H,
                      json={"title": "Prospect conversion deck"}).json()["sid"]
    print("session:", sid)

    banner("4. UPLOAD")
    with XLSX.open("rb") as fh:
        r = client.post(f"/api/sessions/{sid}/upload", headers=H,
                        files=[("files", (XLSX.name, fh,
                                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))])
    print(r.status_code, r.json())

    banner("5. BUILD (async) + POLL STATUS")
    print("build:", client.post(f"/api/sessions/{sid}/build", headers=H, json={}).json())
    for _ in range(60):
        st = client.get(f"/api/sessions/{sid}/status", headers=H).json()
        if not st.get("building"):
            break
        time.sleep(2)
    st = client.get(f"/api/sessions/{sid}/status", headers=H).json()
    print(f"built={st['built']} blocks={st['blocks']} topics={st.get('topics')} "
          f"error={st.get('error')}")
    assert st["built"], f"build failed: {st.get('error')}"

    banner("6. EVENT FEED")
    for e in client.get(f"/api/sessions/{sid}/events", headers=H).json()["events"]:
        print(f"  [{e['stage']}] {e['message']}")

    banner("7. SOURCES")
    print(client.get(f"/api/sessions/{sid}/sources", headers=H).json()["sources"])

    banner("8. SEARCH (graph-augmented)")
    r = client.get(f"/api/sessions/{sid}/search", headers=H,
                   params={"q": "change a prospect status to accepted", "k": 5})
    for h in r.json()["hits"]:
        print(f"  {h['score']:.3f} | {h['title'][:40]} | {h['text'][:55]}")

    banner("9. PLAN — START")
    sess = client.post(f"/api/sessions/{sid}/plan/start", headers=H,
                       json={"request": "beginner training deck on prospect conversion"}).json()
    print(f"status={sess['status']} questions={[q['question'] for q in sess['questions']]}")

    if sess["status"] == "clarifying":
        banner("9b. PLAN — ANSWER")
        answers = {q["id"]: "beginner; prospect conversion" for q in sess["questions"]}
        sess = client.post(f"/api/sessions/{sid}/plan/answer", headers=H,
                           json={"answers": answers}).json()
        print(f"status={sess['status']}")

    plan = sess["plan"]
    print(f"\nDRAFT: '{plan['deck_title']}' — {len(plan['slides'])} slides")
    for s in plan["slides"]:
        print(f"  • {s['title']} ({len(s['bullets'])} bullets)")

    banner("10. PLAN — REVISE")
    sess = client.post(f"/api/sessions/{sid}/plan/revise", headers=H,
                       json={"feedback": "add a slide on converting a prospect to an opportunity"}).json()
    print(f"status={sess['status']} slides={len(sess['plan']['slides'])}")

    banner("11. PLAN — APPROVE")
    sess = client.post(f"/api/sessions/{sid}/plan/approve", headers=H).json()
    print(f"status={sess['status']}")

    banner("12. GENERATE DECK")
    gen = client.post(f"/api/sessions/{sid}/generate", headers=H).json()
    print(f"  file={gen['filename']} slides={gen['slides']} "
          f"bytes={gen['bytes']} url={gen['download_url']}")

    banner("13. DOWNLOAD DECK")
    r = client.get(f"/api/sessions/{sid}/download", headers=H)
    out = BACKEND / "data" / "outputs" / gen["filename"]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(r.content)
    print(f"  saved {len(r.content)} bytes -> {out}")
    assert r.content[:2] == b"PK", "not a valid pptx"

    banner("14. SESSION LIST + CLEANUP")
    print("sessions:", [s["title"] for s in
                        client.get("/api/sessions", headers=H).json()["sessions"]])
    print(client.delete(f"/api/sessions/{sid}", headers=H).json())
    print("\nE2E COMPLETE [OK]")


if __name__ == "__main__":
    main()