"""Recently opened files, kept in the app's settings."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

MAX_RECENT = 8
KEY = "recent"


@dataclass
class RecentFile:
    path: Path
    kind: str  # "Scanned" | "Typed" | "Mixed"
    opened_at: datetime


class RecentFiles:
    def __init__(self, settings) -> None:
        self._settings = settings

    def _load(self) -> list[dict]:
        """Saved entries, skipping anything malformed (a bad value must never stop the app)."""
        try:
            data = json.loads(self._settings.value(KEY, "[]") or "[]")
        except (TypeError, ValueError):
            return []
        if not isinstance(data, list):
            return []
        return [d for d in data if isinstance(d, dict) and isinstance(d.get("path"), str) and d["path"]]

    def add(self, path: Path, kind: str) -> None:
        path = Path(path).resolve()
        entries = [d for d in self._load() if Path(d["path"]) != path]
        entries.insert(0, {"path": str(path), "kind": kind, "opened_at": datetime.now().isoformat()})
        self._settings.setValue(KEY, json.dumps(entries[:MAX_RECENT]))
        self._settings.sync()

    def items(self) -> list[RecentFile]:
        out = []
        for d in self._load():
            path = Path(d["path"])
            if not path.is_file():
                continue  # moved or deleted since
            try:
                when = datetime.fromisoformat(d.get("opened_at", ""))
            except (TypeError, ValueError):
                when = datetime.now()
            kind = d.get("kind") if isinstance(d.get("kind"), str) else ""
            out.append(RecentFile(path, kind, when))
        return out[:MAX_RECENT]

    def clear(self) -> None:
        self._settings.setValue(KEY, "[]")


def relative_day(when: datetime, now: datetime) -> str:
    days = (now.date() - when.date()).days
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 7:
        return f"{days} days ago"
    return f"{when.day} {when.strftime('%b')}"
