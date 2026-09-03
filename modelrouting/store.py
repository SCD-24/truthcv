"""Routing store. Storage: data_dir()/model_routing.json (not secret)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from storage import atomic_write_text, data_dir

TASK_NAMES = ("truth_extract", "keywords", "tailor", "infer", "cover_letter")


def routing_path() -> Path:
    return data_dir() / "model_routing.json"


@dataclass(frozen=True)
class Route:
    connection: str
    model: str = ""
    effort: str = ""
    context_window: int = 0

    @classmethod
    def from_dict(cls, raw: object) -> Route | None:
        """Parse a route dict; unknown/missing fields use defaults.

        Legacy files without an ``effort``/``context_window`` key load unchanged
        (defaulting to ``""``/``0`` respectively).
        """
        if not isinstance(raw, dict) or not isinstance(raw.get("connection"), str):
            return None
        model = raw.get("model")
        effort = raw.get("effort")
        context_window = raw.get("context_window")
        return cls(
            raw["connection"],
            model if isinstance(model, str) else "",
            effort if isinstance(effort, str) else "",
            context_window
            if isinstance(context_window, int) and not isinstance(context_window, bool)
            else 0,
        )

    def to_dict(self) -> dict:
        return {
            "connection": self.connection,
            "model": self.model,
            "effort": self.effort,
            "context_window": self.context_window,
        }


@dataclass
class Routing:
    tasks: dict[str, Route] = field(default_factory=dict)
    agent: Route | None = None
    default: Route | None = None

    @classmethod
    def from_dict(cls, raw: dict) -> Routing:
        tasks: dict[str, Route] = {}
        raw_tasks = raw.get("tasks")
        if isinstance(raw_tasks, dict):
            for name in TASK_NAMES:
                route = Route.from_dict(raw_tasks.get(name))
                if route:
                    tasks[name] = route
        return cls(
            tasks=tasks,
            agent=Route.from_dict(raw.get("agent")),
            default=Route.from_dict(raw.get("default")),
        )

    def to_dict(self) -> dict:
        return {
            "tasks": {k: v.to_dict() for k, v in self.tasks.items()},
            "agent": self.agent.to_dict() if self.agent else None,
            "default": self.default.to_dict() if self.default else None,
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


def resolve(r: Routing, task: str | None) -> Route | None:
    if task and task in r.tasks:
        return r.tasks[task]
    return r.default
