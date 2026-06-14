"""Graph expansion helper for graph-augmented retrieval.

Loads a workspace's `processing/knowledge_graph.json` and answers: "which other
blocks are structurally adjacent to this one?" Two blocks are adjacent when they
share a topic (`part_of`) or a concept (`relates_to`) node. This lets retrieval
pull in blocks that a vector/keyword search missed but that belong to the same
part of the knowledge graph (e.g. the next step in a procedure).
"""
from __future__ import annotations
import json
from collections import defaultdict
from app.core.logging import get_logger
log = get_logger("retrieval")

_GRAPH_REL = "knowledge_graph.json"
# block <-> block adjacency runs through these node types
_GROUP_RELATIONS = {"part_of", "relates_to"}

class GraphExpander:
    """Bipartite block<->group adjacency derived from the knowledge graph."""

    def __init__(self, graph:dict) -> None:
        self._block_to_groups: dict[str, set[str]] = defaultdict(set)
        self._group_to_blocks: dict[str, set[str]] = defaultdict(set)
        for edge in graph.get("edges", []):
            if edge["relation"] not in _GROUP_RELATIONS:
                continue
            src, tgt = edge["source"], edge["target"]
            if src and tgt:
                self._block_to_groups[src].add(tgt)
                self._group_to_blocks[tgt].add(src)

    @property
    def empty(self) -> bool:
        return not self._block_to_groups

    @classmethod
    def from_store(cls, store, ws: str) -> "GraphExpander | None":
        raw = store.get_bytes(ws, "processing", _GRAPH_REL)
        if raw is None:
            return None
        try:
            graph = json.loads(raw)
        except (ValueError, TypeError):
            return None
        exp = cls(graph)
        return None if exp.empty else exp


    def neighbour(self, block_id:str,*,hops:int=5)->set[str]:
        """ Return doc ids( without the blk:: prefix) adjacent to block_id"""
        start = f"blk::{block_id}"
        visited = {start}
        frontier = {start}
        for _ in range(max(1, hops)):
            nxt: set[str] = set()
            for bn in frontier:
                for g in self._block_to_groups.get(bn, ()):
                    for sib in self._group_to_blocks.get(g, ()):
                        if sib not in visited:
                            nxt.add(sib)
            visited |= nxt
            frontier = nxt
            if not frontier:
                break
        return {n[len("blk::"):] for n in visited
                if n != start and n.startswith("blk::")}

