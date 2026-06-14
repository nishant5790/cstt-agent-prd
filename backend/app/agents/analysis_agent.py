"""Agent 3 — Analysis. Turns a request into a grounded DeckPlan.

Grounding sources, in order:
  1. RAG — retriever.query(request, scope) selects the most relevant blocks.
  2. Graph backbone — blocks are grouped by their `topic` node so the deck has
     coherent sections and full topic coverage (never invents facts).
LLM authors the plan from those blocks; a deterministic fallback runs offline.
"""
from __future__ import annotations
import re
from pydantic import BaseModel, Field

from app.agents.kb_loader import load_ckm , load_graph
from app.core import llm
from app.core.base import Agent
from app.core.ckm import CKM , ContentBlock , KnowledgeGraph
from app.core.logging import get_logger
logger = get_logger("analysis")

_AUDIENCES = ("beginner", "intermediate", "experience","advanced","executive")

class SlidePlan(BaseModel):
    title: str
    bullets: list[str] = Field(default_factory=list)
    notes: str = ""
    source_block_ids: list[str] = Field(default_factory=list)

class DeckPlan(BaseModel):
    deck_title: str
    topic: str
    audience: str = "general"
    slides: list[SlidePlan]= Field(default_factory=list)

class AnalysisAgent(Agent):
    name= "analysis"

    def build_plan(self,ws:str, request:str, * , scope:dict|None=None,
                  audience:str|None=None, max_blocks: int=40)-> DeckPlan:
        ckm = load_ckm(ws)
        graph = load_graph(ws) or KnowledgeGraph()

        if ckm is None or not ckm.blocks:
            raise ValueError("Knowledge base not built for this workspace")

        sources = (scope or {}).get("sources", []) or None
        blocks = self._select_blocks(ws, request, ckm, sources, max_blocks)
        audience = audience or self._audience(request)
        topic = self._headline_topic(request, graph, blocks)

        plan = (self._plan_with_llm(request, topic, audience, blocks)
                or self._plan_deterministic(topic, audience, graph, blocks))
        self.log(f"plan '{plan.deck_title}' — {len(plan.slides)} slides, "
                 f"topic={topic}, audience={audience}")
        return plan

    # -- block selection (RAG) ----
    def _select_blocks(self, ws, request, ckm:CKM , sources, max_blocks) -> list[ContentBlock]:
        from app.retrieval import get_retriever
        by_id = {b.id: b for b in ckm.blocks}
        hits = get_retriever().query(ws,request, top_k=max_blocks, sources=sources)
        blocks = [by_id[h.block_id] for h in hits if h.block_id in by_id]
        if blocks:
            return blocks
        pool = [b for b in ckm.blocks if not sources or b.source in set(sources)]
        return pool[:max_blocks]

    # --- topic / audience ---
    def _audience(self, request:str) -> str:
        r = (request or "").lower()
        return next((a for a in _AUDIENCES if a in r), "general")

    def _topic_label_map(self,graph:KnowledgeGraph) -> dict[str, str]:
        return {n.id: n.label for n in graph.nodes if n.type == "topic"}

    def _topic_of(self,graph:KnowledgeGraph,block_id: str) -> str|None:
        bn = f"blk::{block_id}"
        for e in graph.edges:
            if e.source == bn and e.relation == "part_of":
                return e.target
        return None

    def _headline_topic(self,request, graph:KnowledgeGraph,blocks) -> str:
        labels = self._topic_label_map(graph)
        # topic of the strongest (first) retrieved block wins; else most common

        from collections import Counter
        counts:  Counter[str] = Counter()

        for b in blocks:
            tid = self._topic_of(graph, b.id)
            if tid in labels:
                counts[labels[tid]] += 1

        if blocks:
            first = self._topic_of(graph, blocks[0].id)
            if first in labels:
                return labels[first]

        if counts:
            return counts.most_common(1)[0][0]
        return "Training"

    # -- LLM plan --
    def _plan_with_llm(self, request, topic, audience, blocks) -> DeckPlan:
        corpus = "\n".join(f"[{b.id}] {b.title}: {b.text}" for b in blocks)
        data = llm.chat_json(
            system="You are an instructional designer. Build a slide deck plan using "
                   "the provided source blocks ONLY (never invent facts). Each slide "
                   "may cite the block ids it draws from. Reply JSON: "
                   '{"deck_title": str, "slides": [{"title": str, "bullets": [str], '
                   '"notes": str, "source_block_ids": [str]}]}. 5-9 slides incl. a '
                   "title slide and a summary slide.",
            user=f"USER REQUEST: {request}\nTOPIC: {topic}\nAUDIENCE: {audience}\n"
                 f"SOURCE BLOCKS:\n{corpus}",
        )

        if not data or not data["slides"]:
            return None

        slides = [SlidePlan(
            title=str(s.get("title", "")),
            bullets=[str(x) for x in s.get("bullets", [])],
            notes=str(s.get("notes", "")),
            source_block_ids=[str(x) for x in s.get("source_block_ids", [])],
        ) for s in data["slides"]]

        return DeckPlan(
            deck_title=data.get("deck_title", f"{topic} — Training"),
            topic = topic, audience=audience, slides=slides
        )

    # -- deterministic fallback ( graph-backbone) ---

    def _plan_deterministic(self, topic, audience, graph: KnowledgeGraph, blocks) -> DeckPlan:
        labels = self._topic_label_map(graph)
        groups: dict[str, list[ContentBlock]] = {}

        for b in blocks:
            tid = self._topic_of(graph, b.id)
            label = labels.get(tid,topic)
            groups.setdefault(label, []).append(b)
        ordered = sorted(groups.items(), key=lambda kv: len(kv[1]), reverse=True)
        slides = [SlidePlan(title=topic,
                            bullets=[f"Audience: {audience}",
                                     f"Sources: {len({b.source for b in blocks})}",
                                     f"Topics covered: {len(ordered)}"])]

        slides.append(SlidePlan(title="Learning Objectives",
                                bullets=[f"Understand {label}" for label, _ in ordered[:4]]
                                        or [f"Understand {topic}"]))

        for label, grp in ordered[:6]:
            bullets, ids = [], []
            for b in grp[:6]:
                line = (b.text or b.title).strip().replace("\n", " ")
                if line:
                    bullets.append(line[:160])
                    ids.append(b.id)
            if bullets:
                slides.append(SlidePlan(title=label, bullets=bullets, source_block_ids=ids))
        slides.append(SlidePlan(title="Summary & Next Steps",
                                bullets=["Recap of key points", "Practice the steps",
                                         "Where to get help"]))
        return DeckPlan(deck_title=f"{topic} — Training Deck", topic=topic,
                        audience=audience, slides=slides[:9])

