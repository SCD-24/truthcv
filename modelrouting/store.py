"""Routing store. Storage: data_dir()/model_routing.json (not secret)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from storage import atomic_write_text, data_dir

TASK_NAMES = ("truth_extract", "keywords", "tailor", "infer", "cover_letter")

# Agent harness stages that may carry their own route. Adding a stage = one
# entry here + agent/harness/stages.ts + the web AGENT_STAGES list.
AGENT_STAGE_NAMES = ("screening", "extract")


def routing_path() -> Path:
    return data_dir() / "model_routing.json"


@dataclass(frozen=True)
class Route:
    connection: str
    model: str = ""
    effort: str = ""

    @classmethod
    def from_dict(cls, raw: object) -> Route | None:
        """Parse a route dict; unknown/missing fields use defaults.

        Legacy files without an ``effort`` key load unchanged (defaulting to
        ``""``). A legacy ``context_window`` key, if present, is ignored.
        """
        if not isinstance(raw, dict) or not isinstance(raw.get("connection"), str):
            return None
        model = raw.get("model")
        effort = raw.get("effort")
        return cls(
            raw["connection"],
            model if isinstance(model, str) else "",
            effort if isinstance(effort, str) else "",
        )

    def to_dict(self) -> dict:
        return {
            "connection": self.connection,
            "model": self.model,
            "effort": self.effort,
        }


@dataclass
class Routing:
    tasks: dict[str, Route] = field(default_factory=dict)
    agent: Route | None = None
    default: Route | None = None
    agent_stages: dict[str, Route] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict) -> Routing:
        tasks: dict[str, Route] = {}
        raw_tasks = raw.get("tasks")
        if isinstance(raw_tasks, dict):
            for name in TASK_NAMES:
                route = Route.from_dict(raw_tasks.get(name))
                if route:
                    tasks[name] = route
        agent_stages: dict[str, Route] = {}
        raw_stages = raw.get("agent_stages")
        if isinstance(raw_stages, dict):
            for name in AGENT_STAGE_NAMES:
                route = Route.from_dict(raw_stages.get(name))
                if route:
                    agent_stages[name] = route
        return cls(
            tasks=tasks,
            agent=Route.from_dict(raw.get("agent")),
            default=Route.from_dict(raw.get("default")),
            agent_stages=agent_stages,
        )

    def to_dict(self) -> dict:
        return {
            "tasks": {k: v.to_dict() for k, v in self.tasks.items()},
            "agent": self.agent.to_dict() if self.agent else None,
            "default": self.default.to_dict() if self.default else None,
            "agent_stages": {k: v.to_dict() for k, v in self.agent_stages.items()},
        }


def load() -> Routing:
    p = routing_path()
    if not p.exists():
        return Routing()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        return Routing()
    return Routing.from_dict(raw) if isinstance(raw, dict) else Routing()


def save(r: Routing) -> Routing:
    p = routing_path()
    atomic_write_text(p, json.dumps(r.to_dict(), indent=2))
    return r


def resolve_agent_stage(r: Routing, stage: str) -> Route | None:
    """Stage route, else the general agent route, else None."""
    return r.agent_stages.get(stage) or r.agent


def resolve(r: Routing, task: str | None) -> Route | None:
    if task and task in r.tasks:
        return r.tasks[task]
    return r.default
