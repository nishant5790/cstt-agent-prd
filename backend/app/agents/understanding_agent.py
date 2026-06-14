"""Agent 2 — Content Understanding -> Knowledge Graph.

Turns the flat CKM into a graph of topics, concepts and source nodes. Uses the
LLM to label topics/concepts per block when available; otherwise a deterministic
keyword/co-occurrence approach so it runs offline.
"""
from __future__ import annotations

import re
from collections import Counter

from app.core import llm
from app.core.base import Agent , Blackboard
from app.core.ckm import CKM, ContentBlock, Edge, KnowledgeGraph, Node
from app.core.config import settings

# ------- deterministic for no LLM model ---------------------------
_STOP = set("""the a an and or of to in for on with is are be this that as at by from
your you it we will can should into using use step click enter select page row
result expected test case name field value true false none null type id""".split())


def _keywords(text: str, k: int = 5) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9/_-]{2,}", text.lower())
    freq = Counter(w for w in words if w not in _STOP)
    return [w for w, _ in freq.most_common(k)]




class UnderstandingAgent(Agent):
    name = "understanding"

    # --- labelling----

    def _label_blocks(self, blocks: list[ContentBlock])-> dict[str, tuple[str, list[str]]]:
        cfg = settings()
        batch_size = cfg.understanding_batch
        max_llm = cfg.understanding_max_llm_blocks
        use_llm = llm.available() and batch_size > 0 and max_llm > 0
        llm_budget = max_llm if use_llm else 0

        labels: dict[str, tuple[str, list[str]]] = {}
        total = len(blocks)
        self.log(f"labelling {total} block(s) — "
                 f"mode={'LLM+keyword' if use_llm else 'keyword-only'}, "
                 f"batch={batch_size}, llm_budget={llm_budget}")

        i = 0
        while i < len(blocks) and llm_budget > 0:
            batch = blocks[i:i + min(batch_size, llm_budget)]
            got = self._label_batch_llm(batch)
            if got is None:
                self.log("  LLM batch failed — keyword labelling for remainder")
                break
            labels.update(got)
            llm_budget -= len(batch)
            i += len(batch)

        kw_count = 0
        for block in blocks:
            if block.id not in labels:
                labels[block.id] = self._keyword_label(block.title, block.text)
                kw_count += 1
        if kw_count:
            self.log(f"keyword fallback labelled {kw_count} block(s)")
        self.log(f"labelling complete: {len(labels)}/{total} blocks")
        return labels

    def _label_batch_llm(self, batch: list[ContentBlock]):
        items = "\n".join(f"[{n}] {b.title}: {b.text[:300]}" for n, b in enumerate(batch))
        data = llm.chat_json(
            system="You label learning-content snippets. For each numbered item reply "
                   "with its topic and concepts. Reply JSON: "
                   '{"items": [{"i": <int>, "topic": "<2-4 word area>", '
                   '"concepts": ["lowercase noun", ...]}]}. Max 5 concepts each.',
            user=f"ITEMS:\n{items}",
        )

        if not data or "items" not in data:
            return None

        out: dict[str, tuple[str, list[str]]] = {}
        for entry in data["items"]:
            try:
                idx = int(entry["i"])
                block = batch[idx]
            except (KeyError, ValueError, IndexError):
                continue

            topic = str(entry.get("topic") or "").strip()
            concepts = [str(c) for c in (entry.get("concepts") or [])][:5]
            if topic:
                out[block.id] = (topic, concepts)

        for block in batch:
            out.setdefault(block.id, self._keyword_label(block.title, block.text))
        return out

    def _keyword_label(self, title: str, text: str) -> tuple[str, list[str]]:
        kws = _keywords(f"{title} {text}")
        topic = (kws[0].title() if kws else "General")
        return topic, kws[1:5]



    def run(self,bb: Blackboard) -> Blackboard:
        ckm: CKM = bb.get("ckm")
        if ckm is None:
            raise SystemExit("Run ExtractionAgent first!")

        labels = self._label_blocks(ckm.blocks)
        graph = KnowledgeGraph()
        seen: set[str] = set()

        def add_node(node: Node) -> None:
            if node.id not in seen:
                graph.nodes.append(node)
                seen.add(node.id)

        for src in ckm.sources:
            add_node(Node(id=f"src::{src}",type="source",label=src))

        topic_counts: Counter[str]= Counter()
        for block in ckm.blocks:
            topic, concepts = labels[block.id]
            topic_counts[topic] += 1
            tid = f"topic::{re.sub(r'[^a-z0-9]+', '-', topic.lower()).strip('-')}"
            add_node(Node(id=tid, type="topic", label=topic))
            bid = f"blk::{block.id}"
            add_node(Node(
                id=bid,
                type="step" if block.modality in {"table_row", "step"} else "concept",
                label=block.title[:60] or block.text[:60],
                properties={"modality": block.modality, "source": block.source,
                            "timestamp": block.timestamp},
            ))
            graph.edges.append(Edge(source=bid, target=tid, relation="part_of"))
            graph.edges.append(Edge(source=f"src::{block.source}", target=bid, relation="mentions"))
            for c in concepts:
                cid = f"concept::{re.sub(r'[^a-z0-9]+', '-', c.lower()).strip('-')}"
                if cid == tid:
                    continue
                add_node(Node(id=cid, type="concept", label=c))
                graph.edges.append(Edge(source=bid, target=cid, relation="relates_to"))

        bb.set("graph", graph)
        bb.set("topics", [t for t, _ in topic_counts.most_common()])
        bb.save_processing("knowledge_graph.json", graph)
        self.log(f"graph: {len(graph.nodes)} nodes, {len(graph.edges)} edges, "
                 f"{len(topic_counts)} topics")
        return bb

