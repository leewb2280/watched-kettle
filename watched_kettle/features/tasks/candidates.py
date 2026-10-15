"""Bounded explicit-list extraction; no model calls, tools, or writes."""

from __future__ import annotations

from dataclasses import dataclass, replace
import re

from watched_kettle.features.tasks.models import (
    Candidate,
    CompletionCheck,
    TaskSpec,
    source_version,
)


MAX_ANALYSIS_BYTES = 256 * 1024
MAX_ANALYSIS_MESSAGES = 200
MAX_CANDIDATES = 100
CHECKBOX = re.compile(r"^\s{0,3}[-*+]\s+\[([ xX~-])\]\s+(.+)$")
NUMBERED = re.compile(r"^\s{0,3}\d+[.)]\s+(.+)$")
PLAN_HEADING = re.compile(
    r"^(?:#{1,6}\s*)?(?:확정된?\s*)?(?:계획|할 일|작업 계획|실행 계획|plan|tasks|todo)\s*:?.*$",
    re.I,
)
TERMINAL = re.compile(
    r"(?:완료(?:했어|했다|됨|했음|했습니다)?|취소(?:해|했어|합니다|해줘)?|제외(?:해|해줘)?|하지\s*마|중단(?:해|해줘)?|거절(?:했어)?|\b(?:cancelled|canceled|completed|rejected))\s*[.!]?$",
    re.I,
)


@dataclass(frozen=True)
class Extraction:
    candidates: tuple[Candidate, ...]
    truncated: bool
    messages_read: int
    bytes_read: int


def _text(item: dict) -> str:
    if item.get("type") == "agentMessage":
        return str(item.get("text", ""))
    content = item.get("content", [])
    if not isinstance(content, list):
        return ""
    return "\n".join(
        str(part.get("text", ""))
        for part in content
        if isinstance(part, dict) and part.get("type") in {"text", "inputText"}
    )


def candidate_key(text: str) -> str:
    return " ".join(text.split()).casefold()


class CandidateAccumulator:
    """Incremental explicit-list parser; only candidate excerpts survive a page."""

    def __init__(self, thread):
        self.thread = thread
        self.candidates: dict[str, Candidate] = {}
        self.count = 0
        self.size = 0
        self.truncated = False

    def feed(self, turn_id, item):
        role = item.get("type")
        if role not in {"userMessage", "agentMessage"}:
            return
        text = _text(item)
        self.count += 1
        self.size += len(text.encode("utf-8"))
        fenced, fence_char, in_plan = False, "", False
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith(("```", "~~~")):
                if not fenced:
                    fenced, fence_char = True, stripped[0]
                elif stripped[0] == fence_char:
                    fenced = False
                continue
            if fenced or line.startswith(("    ", "\t")) or stripped.startswith(">"):
                continue
            if PLAN_HEADING.fullmatch(stripped):
                in_plan = True
                continue
            if stripped.startswith("#"):
                in_plan = False
            checkbox = CHECKBOX.match(line)
            numbered = NUMBERED.match(line) if in_plan else None
            if not checkbox and not numbered:
                # Only a complete exact task mention with an explicit terminal suffix.
                match = TERMINAL.search(stripped)
                if match:
                    mention = candidate_key(stripped[: match.start()].strip(" :—-"))
                    for suffix in ("은", "는", "을", "를"):
                        if mention.endswith(suffix) and mention[:-1] in self.candidates:
                            mention = mention[:-1]
                            break
                    self.terminal(
                        mention,
                        role,
                        "취소" not in stripped and "cancel" not in stripped.lower(),
                    )
                continue
            if checkbox:
                value = checkbox.group(2).strip()
            elif numbered:
                value = numbered.group(1).strip()
            else:
                continue
            key = candidate_key(value)
            if checkbox and checkbox.group(1) != " ":
                self.terminal(key, role, checkbox.group(1).lower() == "x")
                continue
            if len(value) > 240:
                continue
            previous = self.candidates.get(key)
            confirmed = role == "userMessage"
            if previous and previous.confirmed_plan and not confirmed:
                continue
            if previous is None and len(self.candidates) >= MAX_CANDIDATES:
                self.truncated = True
                continue
            self.candidates[key] = Candidate(
                TaskSpec(
                    value,
                    value,
                    str(self.thread.get("projectId") or ""),
                    str(self.thread.get("id") or ""),
                    str(self.thread.get("cwd") or ""),
                    "",
                    source_refs=(str(turn_id), str(item.get("id", ""))),
                    checks=(CompletionCheck("작업 결과를 사용자가 확인"),),
                    source_candidate=key,
                ),
                "사용자의 명시적 계획"
                if confirmed
                else "미확정 제안 — 등록 전 검토 필요",
                stripped[:500],
                confirmed,
            )

    def terminal(self, key, role, completed):
        previous = self.candidates.get(key)
        if previous is None:
            return
        if role == "userMessage":
            self.candidates.pop(key)
        elif completed:
            self.candidates[key] = replace(
                previous, reported_complete=True, reason="완료 보고됨 — 원문에서 확인"
            )

    def finish(self, version):
        return Extraction(
            tuple(
                replace(c, spec=replace(c.spec, source_version=version))
                for c in self.candidates.values()
            ),
            self.truncated,
            self.count,
            self.size,
        )


def extract_candidates(thread: dict, project_id: str = "") -> Extraction:
    turns = thread.get("turns", [])
    if not isinstance(turns, list):
        return Extraction((), False, 0, 0)
    if any(
        not isinstance(t, dict)
        or not isinstance(t.get("items", []), list)
        or any(not isinstance(i, dict) for i in t.get("items", []))
        for t in turns
    ):
        return Extraction((), True, 0, 0)
    # Refuse oversized input rather than silently missing a later cancellation.
    size = sum(
        len(_text(i).encode("utf-8"))
        for t in turns
        for i in t.get("items", [])
        if isinstance(i, dict)
    )
    count = sum(len(t.get("items", [])) for t in turns)
    if size > MAX_ANALYSIS_BYTES or count > MAX_ANALYSIS_MESSAGES:
        return Extraction((), True, 0, 0)
    parser = CandidateAccumulator(
        {**thread, "projectId": project_id or thread.get("projectId")}
    )
    for turn in turns:
        for item in turn.get("items", []):
            parser.feed(turn.get("id", ""), item)
    return parser.finish(source_version(turns))
