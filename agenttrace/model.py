"""Core normalized trace model, agent-neutral and JSON-serializable.

A `Trace` is one agent run. It nests as Trace -> Turn -> Event. Payload
specifics live in `Event.data` so the model stays small while carrying
agent details without a schema change.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field


EVENT_TYPES = ("reasoning", "tool_call", "tool_result", "error", "meta", "unknown")


@dataclass
class Event:
    id: str
    type: str
    timestamp: str | None
    raw: dict | None
    data: dict

    def to_dict(self) -> dict:
        return {"id": self.id, "type": self.type, "timestamp": self.timestamp,
                "raw": self.raw, "data": self.data}

    @classmethod
    def from_dict(cls, d: dict) -> "Event":
        return cls(id=d.get("id", ""), type=d.get("type", "unknown"),
                   timestamp=d.get("timestamp"), raw=d.get("raw"),
                   data=d.get("data", {}))


@dataclass
class Turn:
    seq: int
    events: list[Event]
    meta: dict

    def to_dict(self) -> dict:
        return {"seq": self.seq, "events": [e.to_dict() for e in self.events],
                "meta": self.meta}

    @classmethod
    def from_dict(cls, d: dict) -> "Turn":
        return cls(seq=d.get("seq", 0),
                   events=[Event.from_dict(e) for e in d.get("events", [])],
                   meta=d.get("meta", {}))


@dataclass
class Trace:
    run_id: str | None
    agent: str
    seed: dict
    turns: list[Turn]
    incomplete: bool = False
    started_at: str | None = None
    ended_at: str | None = None
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"run_id": self.run_id, "agent": self.agent, "seed": self.seed,
                "turns": [t.to_dict() for t in self.turns],
                "incomplete": self.incomplete, "started_at": self.started_at,
                "ended_at": self.ended_at, "meta": self.meta}

    @classmethod
    def from_dict(cls, d: dict) -> "Trace":
        return cls(run_id=d.get("run_id"), agent=d.get("agent", "unknown"),
                   seed=d.get("seed", {"system_prompt": None, "user_input": None}),
                   turns=[Turn.from_dict(t) for t in d.get("turns", [])],
                   incomplete=d.get("incomplete", False),
                   started_at=d.get("started_at"), ended_at=d.get("ended_at"),
                   meta=d.get("meta", {}))

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_json(cls, s: str) -> "Trace":
        return cls.from_dict(json.loads(s))
