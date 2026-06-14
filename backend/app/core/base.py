"""Tiny agent runtime: a shared Blackboard + a minimal Agent base class.

Every agent reads/writes the same Blackboard, so stages are composable and
re-runnable. State is persisted to disk as JSON.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.logging import get_logger

@dataclass
class Blackboard:
    """Shared state passed between agents. Persisted as JSON."""

    workdir: Path
    processing_dir: Path | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value

    def save(self, name: str, payload: Any) -> Path:
        return self._write(self.workdir / name, payload)

    def save_processing(self, name: str, payload: Any) -> Path:
        base = self.processing_dir or self.workdir
        return self._write(base / name, payload)

    @staticmethod
    def _write(out: Path, payload: Any) -> Path:
        out.parent.mkdir(parents=True, exist_ok=True)
        if hasattr(payload, "model_dump"):
            payload = payload.model_dump()
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return out


class Agent:
    """Base class. Each agent has a name and a run(bb) method."""

    name: str = "agent"

    @property
    def logger(self):
        return get_logger(self.name)

    def log(self, msg: str) -> None:
        self.logger.info(msg)

    def run(self, bb: Blackboard) -> Blackboard:  # interface
        raise NotImplementedError