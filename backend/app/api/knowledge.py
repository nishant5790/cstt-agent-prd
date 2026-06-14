"""Knowledge-base routes — workspace-scoped, store-backed, multi-instance safe.

Per request a workspace id (X-Workspace-Id) isolates all data. Sources and
artifacts live in the storage backend (local fs or Azure Blob); workspace state
lives in the state backend (local json or Azure Table). A build runs in a
throwaway temp working dir that is synced to the store, so any replica can serve
any follow-up request.
"""
from __future__ import annotations

import tempfile
import threading
import time
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app import connectors, tools
from app.agents.extraction_agent import ExtractionAgent
from app.agents.understanding_agent import UnderstandingAgent
from app.api.deps import session_owner
from app.core import llm
from app.core.base import Blackboard
from app.core.ckm import CKM
from app.jobs import enqueue_build
from app.retrieval import get_retriever
from app.state import get_state
from app.api.deps import is_valid_workspace_id

router = APIRouter(prefix="/api", tags=["knowledge"])

SUPPORTED_SUFFIXES = tools.supported_suffixes()
_state = get_state()

# guards against two concurrent builds for the same workspace within a replica
_build_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _build_lock(ws: str) -> threading.Lock:
    with _locks_guard:
        return _build_locks.setdefault(ws, threading.Lock())


def _event(ws: str, stage: str, message: str) -> None:
    """Append a build/agent event to the session's capped event log."""
    state = _state.get_workspace(ws)
    events = state.get("events", [])
    events.append({"ts": time.time(), "stage": stage, "message": message})
    _state.update_workspace(ws, events=events[-100:])


class BuildIn(BaseModel):
    jira_jql: str | None = None
    sp_folder: str | None = None

# ----------------------------------------------------------------- build worker
def _build_worker(ws: str, jira_jql: str | None, sp_folder: str | None) -> None:
    from app.storage import get_store
    store = get_store()
    lock = _build_lock(ws)
    if not lock.acquire(blocking=False):
        return  # a build for this workspace is already running here
    try:
        _event(ws, "build", "build started")
        with tempfile.TemporaryDirectory(prefix=f"build-{ws}-") as tmp:
            tmp_path = Path(tmp)
            inputs = tmp_path / "inputs"
            processing = tmp_path / "processing"
            outputs = tmp_path / "outputs"
            for d in (inputs, processing, outputs):
                d.mkdir(parents=True, exist_ok=True)

            # 1. pull this workspace's sources into the working dir
            store.download_category(ws, "inputs", inputs)

            # 2. run the unchanged agent pipeline against the working dir
            bb = Blackboard(workdir=outputs, processing_dir=processing)
            ExtractionAgent(inputs).run(bb)
            _event(ws, "extract", "sources extracted into content blocks")

            extra = connectors.fetch_all(jira_jql=jira_jql, sp_folder=sp_folder)
            if extra:
                ckm = bb.get("ckm")
                seen = set(ckm.sources)
                for b in extra:
                    if b.source not in seen:
                        ckm.sources.append(b.source)
                        seen.add(b.source)
                ckm.blocks.extend(extra)
                bb.set("ckm", ckm)
                bb.save_processing("ckm.json", ckm)
            UnderstandingAgent().run(bb)
            _event(ws, "understand", "knowledge graph built")
            # 3. push artifacts (ckm.json, graph, transcripts, assets) back to store
            store.upload_category(ws, "processing", processing)

            ckm: CKM = bb.get("ckm")
            if ckm and ckm.blocks:
                get_retriever().index(ws, ckm.blocks)
                _event(ws, "index", f"indexed {len(ckm.blocks)} blocks")

            _state.update_workspace(
                ws, built=True, building=False, error=None,
                topics=bb.get("topics", []),
                blocks=len(ckm.blocks) if ckm else 0,
                sources=ckm.sources if ckm else [])
            _event(ws, "build", "build complete")
    except Exception as exc:
        _state.update_workspace(ws, built=False, building=False, error=str(exc))
        _event(ws, "error", f"build failed: {exc}")
    finally:
        lock.release()

# ----------------------------------------------------------------- routes
@router.get("/sessions/{sid}/status")
def status(ws: str = Depends(session_owner)) -> dict:
    state = _state.get_workspace(ws)
    return dict(state, workspace=ws, llm=llm.available())


@router.get("/sessions/{sid}/events")
def events(since: int = 0, ws: str = Depends(session_owner)) -> dict:
    evs = _state.get_workspace(ws).get("events", [])
    since = max(0, since)
    return {"events": evs[since:], "total": len(evs)}


@router.get("/sessions/{sid}/sources")
def list_sources(ws: str = Depends(session_owner)) -> dict:
    from app.storage import get_store
    files = get_store().list(ws, "inputs")
    return {"sources": files, "supported": sorted(SUPPORTED_SUFFIXES)}


@router.post("/sessions/{sid}/upload")
async def upload(ws: str = Depends(session_owner),
                 files: list[UploadFile] = File(...)) -> dict:
    from app.storage import get_store
    store = get_store()
    saved, skipped = [], []
    for uf in files:
        name = Path(uf.filename or "").name
        if not name or Path(name).suffix.lower() not in SUPPORTED_SUFFIXES:
            skipped.append(name or "(unnamed)")
            continue
        data = await uf.read()
        store.put_bytes(ws, "inputs", name, data)
        saved.append(name)
    if saved:
        _state.update_workspace(ws, built=False, topics=[], blocks=0, sources=[])
        _event(ws, "upload", f"uploaded {len(saved)} file(s): {', '.join(saved)}")
    return {"ok": True, "saved": saved, "skipped": skipped, "workspace": ws}


@router.delete("/sessions/{sid}/sources/{name}")
def delete_source(name: str, ws: str = Depends(session_owner)) -> dict:
    from app.storage import get_store
    store = get_store()
    safe = Path(name).name
    if Path(safe).suffix.lower() not in SUPPORTED_SUFFIXES or not store.exists(ws, "inputs", safe):
        raise HTTPException(404, "Source not found")
    store.delete(ws, "inputs", safe)
    _state.update_workspace(ws, built=False, topics=[], blocks=0, sources=[])
    return {"ok": True, "deleted": safe}


@router.post("/sessions/{sid}/build")
def build(body: BuildIn | None = None, ws: str = Depends(session_owner)) -> dict:
    state = _state.get_workspace(ws)
    if state.get("building"):
        return {"ok": True, "building": True, "workspace": ws}
    _state.update_workspace(ws, building=True, built=False, error=None)
    jql = body.jira_jql if body else None
    folder = body.sp_folder if body else None
    enqueue_build(ws, jql, folder)
    return {"ok": True, "building": True, "workspace": ws}


@router.get("/sessions/{sid}/search")
def search(q: str, k: int = 8, sources: str | None = None, graph: bool = True,
           ws: str = Depends(session_owner)) -> dict:
    state = _state.get_workspace(ws)
    if not state.get("built"):
        raise HTTPException(409, "Knowledge base not built yet")
    src_list = [s.strip() for s in sources.split(",") if s.strip()] if sources else None
    hits = get_retriever().query(ws, q, top_k=max(1, min(k, 50)),
                                 sources=src_list, graph_expand=graph)
    return {"query": q, "workspace": ws, "sources": src_list, "graph": graph,
            "hits": [h.to_dict() for h in hits]}

@router.get("/workspaces/{ws}/download/{category}/{rel:path}")
def download(ws: str, category: str, rel: str) -> FileResponse:
    """Serve a stored file in local mode. In Azure mode the frontend should use
    the SAS URL from `Storage.download_url` instead of this route."""
    from app.storage import get_store
    if category not in ("inputs", "processing", "outputs"):
        raise HTTPException(404, "Unknown category")
    store = get_store()
    data = store.get_bytes(ws, category, rel)  # type: ignore[arg-type]
    if data is None:
        raise HTTPException(404, "Not found")
    # write to a temp file for FileResponse streaming
    tmp = Path(tempfile.gettempdir()) / f"dl-{ws}-{Path(rel).name}"
    tmp.write_bytes(data)
    return FileResponse(tmp, filename=Path(rel).name)

# ----------------------------------------------------------------- admin
@router.get("/workspaces")
def list_workspaces() -> dict:
    """List all known workspace ids (admin / debug)."""
    return {"workspaces": _state.list_workspaces()}


@router.delete("/workspaces/{ws}")
def delete_workspace(ws: str) -> dict:
    """Purge a workspace: every stored file plus its state and sessions."""
    if not is_valid_workspace_id(ws):
        raise HTTPException(400, "Invalid workspace id")
    from app.storage import get_store
    store = get_store()
    deleted = 0
    for category in ("inputs", "processing", "outputs"):
        for f in store.list(ws, category):
            store.delete(ws, category, f["name"])
            deleted += 1
    try:
        get_retriever().clear(ws)
    except Exception:
        pass
    _state.delete_workspace(ws)
    return {"ok": True, "workspace": ws, "files_deleted": deleted}

