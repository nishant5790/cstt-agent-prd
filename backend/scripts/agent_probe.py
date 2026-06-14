from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.agents.analysis_agent import AnalysisAgent
from app.agents.conversation_agent import ConversationPlanner
from app.agents.extraction_agent import ExtractionAgent
from app.agents.ppt_agent import PptAgent
from app.agents.understanding_agent import UnderstandingAgent
from app.core import llm
from app.core.base import Blackboard
from app.retrieval import get_retriever
from app.state import get_state
from app.storage import get_store


def _set_local_backends() -> None:
    os.environ["STORAGE_BACKEND"] = "local"
    os.environ["STATE_BACKEND"] = "local"
    os.environ["RETRIEVAL_BACKEND"] = "local"
    os.environ["QUEUE_BACKEND"] = "local"


def _reset_singletons() -> None:
    from app.retrieval import get_retriever as _gr
    from app.state import get_state as _gs
    from app.storage import get_store as _gst

    _gr.cache_clear()
    _gs.cache_clear()
    _gst.cache_clear()


def _ensure_inputs(inputs_dir: Path) -> list[Path]:
    if not inputs_dir.exists():
        raise FileNotFoundError(f"inputs directory does not exist: {inputs_dir}")
    files = sorted([p for p in inputs_dir.iterdir() if p.is_file()])
    if not files:
        raise FileNotFoundError(f"no input files found in: {inputs_dir}")
    return files


def _copy_inputs_to_store(ws: str, files: list[Path]) -> None:
    store = get_store()
    for p in files:
        store.put_file(ws, "inputs", p.name, p)


def _save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _plan_metrics(plan: dict) -> dict[str, Any]:
    slides = plan.get("slides", [])
    source_ids = []
    bullets = 0
    for s in slides:
        bullets += len(s.get("bullets", []))
        source_ids.extend(s.get("source_block_ids", []))
    return {
        "slides": len(slides),
        "total_bullets": bullets,
        "unique_source_block_ids": len(set(source_ids)),
    }


def run_probe(
    *,
    workspace: str,
    inputs_dir: Path,
    request: str,
    audience: str | None = None,
    top_k: int = 8,
    max_blocks: int = 40,
    out_dir: Path | None = None,
    force_local: bool = True,
    run_planner: bool = True,
    planner_auto_answer: str = "beginner audience",
) -> dict[str, Any]:
    if force_local:
        _set_local_backends()
    _reset_singletons()

    state = get_state()
    retriever = get_retriever()

    files = _ensure_inputs(inputs_dir)
    _copy_inputs_to_store(workspace, files)

    with tempfile.TemporaryDirectory(prefix=f"agent-probe-{workspace}-") as tmp:
        tmp_path = Path(tmp)
        local_inputs = tmp_path / "inputs"
        local_processing = tmp_path / "processing"
        local_outputs = tmp_path / "outputs"
        for d in (local_inputs, local_processing, local_outputs):
            d.mkdir(parents=True, exist_ok=True)

        for src in files:
            shutil.copy2(src, local_inputs / src.name)

        started = time.time()
        bb = Blackboard(workdir=local_outputs, processing_dir=local_processing)

        # 1) Extraction
        ExtractionAgent(local_inputs).run(bb)
        ckm = bb.get("ckm")
        if ckm is None or not ckm.blocks:
            raise RuntimeError("extraction produced no content blocks")

        # 2) Understanding
        UnderstandingAgent().run(bb)
        graph = bb.get("graph")
        topics = bb.get("topics", [])

        # Persist processing artifacts so AnalysisAgent can load via kb_loader.
        store = get_store()
        store.upload_category(workspace, "processing", local_processing)

        indexed = retriever.index(workspace, ckm.blocks)
        state.update_workspace(
            workspace,
            built=True,
            building=False,
            error=None,
            blocks=len(ckm.blocks),
            topics=topics,
            sources=ckm.sources,
        )

        # 3) Search diagnostics
        hits = retriever.query(workspace, request, top_k=top_k)

        # 4) Analysis agent plan
        plan_obj = AnalysisAgent().build_plan(
            workspace,
            request,
            audience=audience,
            max_blocks=max_blocks,
        )
        plan = plan_obj.model_dump()

        # 5) PPT generation
        ppt = PptAgent()
        deck_bytes = ppt.build(plan_obj)
        deck_name = "probe-deck.pptx"
        store.put_bytes(workspace, "outputs", deck_name, deck_bytes)

        planner_result: dict[str, Any] | None = None
        if run_planner:
            planner = ConversationPlanner()
            p = planner.start(workspace, request, audience=audience)
            if p.get("status") == "clarifying" and p.get("questions"):
                answers = {q["id"]: planner_auto_answer for q in p["questions"]}
                p = planner.answer(workspace, p["sid"], answers)
            planner_result = p

        elapsed = round(time.time() - started, 3)

    report = {
        "workspace": workspace,
        "inputs_dir": str(inputs_dir),
        "input_files": [p.name for p in files],
        "llm_available": llm.available(),
        "embeddings_available": llm.embeddings_available(),
        "request": request,
        "audience": audience,
        "elapsed_seconds": elapsed,
        "extraction": {
            "sources": len(ckm.sources),
            "blocks": len(ckm.blocks),
            "blocks_with_visuals": sum(1 for b in ckm.blocks if b.image_ref),
            "modalities": sorted({b.modality for b in ckm.blocks}),
        },
        "understanding": {
            "topics": topics,
            "topic_count": len(topics),
            "graph_nodes": len(graph.nodes) if graph else 0,
            "graph_edges": len(graph.edges) if graph else 0,
        },
        "indexing": {
            "indexed_blocks": indexed,
            "top_k": top_k,
            "search_hits": [h.to_dict() for h in hits],
        },
        "analysis": {
            "deck_title": plan.get("deck_title"),
            "topic": plan.get("topic"),
            "audience": plan.get("audience"),
            "metrics": _plan_metrics(plan),
            "plan": plan,
        },
        "ppt": {
            "bytes": len(deck_bytes),
            "store_rel": deck_name,
        },
        "planner": planner_result,
    }

    if out_dir is None:
        out_dir = BACKEND_ROOT / "data" / "agent_probe" / workspace
    out_dir.mkdir(parents=True, exist_ok=True)

    _save_json(out_dir / "report.json", report)
    _save_json(out_dir / "plan.json", report["analysis"]["plan"])
    _save_json(
        out_dir / "search_hits.json",
        {"hits": report["indexing"]["search_hits"], "request": request},
    )
    if planner_result is not None:
        _save_json(out_dir / "planner_session.json", planner_result)

    return report


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Run extraction/understanding/retrieval/analysis/ppt (and optional "
            "conversation planner) for one workspace and write tuning diagnostics."
        )
    )
    p.add_argument("--workspace", default="agent-probe")
    p.add_argument(
        "--inputs-dir",
        default=str(BACKEND_ROOT / "data" / "inputs"),
        help="Directory with source files to test.",
    )
    p.add_argument(
        "--request",
        default="Create a beginner training deck from these materials.",
    )
    p.add_argument("--audience", default=None)
    p.add_argument("--top-k", type=int, default=8)
    p.add_argument("--max-blocks", type=int, default=40)
    p.add_argument(
        "--out-dir",
        default=None,
        help="Output folder for report.json/plan.json/search_hits.json.",
    )
    p.add_argument(
        "--respect-env",
        action="store_true",
        help="Do not force local backends; use current environment backends.",
    )
    p.add_argument(
        "--skip-planner",
        action="store_true",
        help="Skip the conversation planner stage.",
    )
    p.add_argument(
        "--planner-auto-answer",
        default="beginner audience",
        help="Auto-answer used when planner asks clarification questions.",
    )
    return p


def main() -> None:
    args = _build_parser().parse_args()
    out_dir = Path(args.out_dir) if args.out_dir else None
    report = run_probe(
        workspace=args.workspace,
        inputs_dir=Path(args.inputs_dir),
        request=args.request,
        audience=args.audience,
        top_k=max(1, args.top_k),
        max_blocks=max(1, args.max_blocks),
        out_dir=out_dir,
        force_local=not args.respect_env,
        run_planner=not args.skip_planner,
        planner_auto_answer=args.planner_auto_answer,
    )
    print("[OK] Agent probe finished")
    print(f"workspace={report['workspace']}")
    print(f"inputs={len(report['input_files'])} files")
    print(f"blocks={report['extraction']['blocks']} | topics={report['understanding']['topic_count']}")
    print(f"slides={report['analysis']['metrics']['slides']} | deck_bytes={report['ppt']['bytes']}")


if __name__ == "__main__":
    main()
