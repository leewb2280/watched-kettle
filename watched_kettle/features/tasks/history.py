"""One bounded history read at a time, with atomic candidate publication."""

from PySide6.QtCore import QObject, Signal, QTimer

from watched_kettle.features.tasks.candidates import (
    CandidateAccumulator,
    extract_candidates,
    MAX_ANALYSIS_BYTES,
    MAX_ANALYSIS_MESSAGES,
)
from watched_kettle.features.tasks.models import SourceVersion, source_version


class HistoryReader(QObject):
    completed = Signal(object)
    failed = Signal(str, str)
    progress = Signal(str, str)

    def __init__(self, client, parent=None):
        super().__init__(parent)
        self.client = client
        self.identity = ""
        self.pending = None
        self.epoch = 0
        self.metadata = {}
        self.turns = []
        self.next_turns = None
        self.current_turn = {}
        self.cursors = set()
        self.version = SourceVersion()
        self.parser = CandidateAccumulator({})
        self.fallback = False
        self.items = []
        self.next_items = None
        self.seen_turns = set()
        self.excluded_turns = set()
        self.baseline = SourceVersion()
        self.evidence_turn_id = ""
        self.evidence_turn = None
        self.command_targets = set()
        self.command_evidence = {}
        client.response_received.connect(self.response)

    def cancel(self):
        self.epoch += 1
        self.pending = None
        self.identity = ""
        self.metadata = {}
        self.turns.clear()
        self.current_turn = {}
        self.cursors.clear()
        self.items.clear()
        self.seen_turns.clear()
        self.parser = CandidateAccumulator({})
        self.excluded_turns.clear()
        self.evidence_turn_id = ""
        self.evidence_turn = None
        self.command_targets.clear()
        self.command_evidence.clear()

    def start(
        self, identity, *, excluded_turns=(), evidence_turn_id="", command_targets=()
    ):
        if self.identity:
            raise ValueError("history_read_busy")
        self.cancel()
        self.identity = identity
        self.version = SourceVersion()
        self.baseline = SourceVersion()
        self.excluded_turns = set(excluded_turns)
        self.evidence_turn_id = evidence_turn_id
        self.command_targets = set(command_targets)
        self.fallback = False
        self.progress.emit(identity, "대화 읽는 중")
        self.request(
            "metadata", "thread/read", {"threadId": identity, "includeTurns": False}
        )

    def request(self, kind, method, params):
        rid = self.client.request(method, params)
        if rid is None:
            self.fail("대화 연결을 확인할 수 없습니다.")
        else:
            self.pending = (rid, kind)

    def fail(self, message):
        identity = self.identity
        self.cancel()
        self.failed.emit(identity, message)

    def cursor(self, kind, result):
        value = result.get("nextCursor")
        if value is None or value == "":
            return None
        marker = (kind, self.current_turn.get("id") if kind == "items" else "", value)
        if (
            not isinstance(value, str)
            or marker in self.cursors
            or len(self.cursors) >= 10000
        ):
            raise ValueError("invalid_cursor")
        self.cursors.add(marker)
        return value

    def turn_page(self, cursor=None):
        self.request(
            "turns",
            "thread/turns/list",
            {
                "threadId": self.identity,
                "limit": 20,
                "itemsView": "notLoaded",
                "sortDirection": "asc",
                "cursor": cursor,
            },
        )

    def item_page(self, cursor=None):
        self.request(
            "items",
            "thread/items/list",
            {
                "threadId": self.identity,
                "turnId": self.current_turn["id"],
                "limit": 100,
                "sortDirection": "asc",
                "cursor": cursor,
            },
        )

    def next_turn(self):
        if self.turns:
            self.current_turn = self.turns.pop(0)
            if self.current_turn["id"] in self.seen_turns:
                self.fail("분석하지 못함 — 같은 대화 턴이 반복되었습니다.")
                return
            self.seen_turns.add(self.current_turn["id"])
            self.version.turn(self.current_turn)
            if self.current_turn["id"] not in self.excluded_turns:
                self.baseline.turn(self.current_turn)
            if self.current_turn["id"] == self.evidence_turn_id:
                self.evidence_turn = {**self.current_turn, "items": []}
            self.item_page()
        elif self.next_turns:
            self.turn_page(self.next_turns)
        else:
            self.request(
                "verify",
                "thread/read",
                {"threadId": self.identity, "includeTurns": False},
            )

    def later(self, callback):
        epoch = self.epoch
        QTimer.singleShot(
            0, lambda: callback() if self.epoch == epoch and self.identity else None
        )

    def consume_items(self):
        count, size = 0, 0
        while (
            self.items and count < MAX_ANALYSIS_MESSAGES and size < MAX_ANALYSIS_BYTES
        ):
            item = self.items.pop(0)
            before = self.parser.size
            self.version.item(item)
            if self.current_turn["id"] not in self.excluded_turns:
                self.baseline.item(item)
            self.collect_evidence(self.current_turn["id"], item)
            self.parser.feed(self.current_turn["id"], item)
            size += max(1, self.parser.size - before)
            count += 1
        self.progress.emit(
            self.identity, f"명시적 할 일 확인 중 · 메시지 {self.parser.count}개"
        )
        if self.items:
            self.later(self.consume_items)
        elif self.next_items:
            self.later(lambda: self.item_page(self.next_items))
        else:
            self.later(self.next_turn)

    def collect_evidence(self, turn_id, item):
        if turn_id != self.evidence_turn_id or item.get("type") != "commandExecution":
            return
        if not isinstance(item.get("command"), str) or not isinstance(
            item.get("cwd"), str
        ):
            return
        key = (item.get("command"), item.get("cwd"))
        if key in self.command_targets:
            self.command_evidence[key] = {
                k: item.get(k) for k in ("type", "command", "cwd", "status", "exitCode")
            }

    def response(self, rid, _method, _params, result, error):
        if self.pending is None or rid != self.pending[0]:
            return
        _, kind = self.pending
        self.pending = None
        if error:
            # Unsupported pagination may fall back; auth/timeouts/schema faults may not.
            message = str(error.get("message", "")).lower()
            unsupported = (
                error.get("code") in {-32601, -32602}
                or "does not support" in message
                or "not supported" in message
            )
            if kind in {"turns", "items"} and unsupported and not self.fallback:
                self.fallback = True
                self.turns.clear()
                self.parser = CandidateAccumulator(self.metadata)
                self.request(
                    "full",
                    "thread/read",
                    {"threadId": self.identity, "includeTurns": True},
                )
            else:
                self.fail("분석하지 못함 — 대화 조회가 실패했습니다. 다시 시도하세요.")
            return
        try:
            if not isinstance(result, dict):
                raise ValueError("invalid_result")
            if kind in {"metadata", "verify", "full"}:
                thread = result.get("thread")
                if not isinstance(thread, dict) or thread.get("id") != self.identity:
                    raise ValueError("invalid_identity")
                if kind == "metadata":
                    self.metadata = {
                        k: thread.get(k)
                        for k in (
                            "id",
                            "name",
                            "projectId",
                            "cwd",
                            "updatedAt",
                            "status",
                            "canAcceptDirectInput",
                        )
                    }
                    self.parser = CandidateAccumulator(self.metadata)
                    self.turn_page()
                else:
                    if any(
                        thread.get(k) != self.metadata.get(k)
                        for k in ("projectId", "cwd", "updatedAt")
                    ):
                        self.fail("분석 중 대화가 변경되었습니다. 다시 읽어주세요.")
                        return
                    if kind == "full":
                        if not isinstance(thread.get("turns"), list):
                            raise ValueError("invalid_turns")
                        extraction = extract_candidates(thread)
                        if extraction.truncated and extraction.messages_read == 0:
                            self.fail(
                                "분석하지 못함 — 이 저장소는 긴 대화의 페이지 조회를 지원하지 않습니다."
                            )
                            return
                        version = source_version(thread["turns"])
                        baseline = source_version(
                            [
                                t
                                for t in thread["turns"]
                                if t.get("id") not in self.excluded_turns
                            ]
                        )
                        for turn in thread["turns"]:
                            if turn.get("id") == self.evidence_turn_id:
                                self.evidence_turn = {
                                    "id": turn["id"],
                                    "status": turn.get("status"),
                                    "items": [],
                                }
                                for item in turn.get("items", []):
                                    self.collect_evidence(turn["id"], item)
                    else:
                        version = self.version.value()
                        baseline = self.baseline.value()
                        extraction = self.parser.finish(version)
                    if self.evidence_turn is not None:
                        self.evidence_turn["items"] = list(
                            self.command_evidence.values()
                        )
                    output = {
                        **self.metadata,
                        "status": thread.get("status"),
                        "canAcceptDirectInput": thread.get("canAcceptDirectInput"),
                        "sourceVersion": version,
                        "baselineVersion": baseline,
                        "executionTurn": self.evidence_turn,
                        "extraction": extraction,
                    }
                    self.cancel()
                    self.completed.emit(output)
            elif kind == "turns":
                rows = result.get("data")
                if (
                    not isinstance(rows, list)
                    or len(rows) > 200
                    or any(
                        not isinstance(t, dict) or not isinstance(t.get("id"), str)
                        for t in rows
                    )
                ):
                    raise ValueError("invalid_turn_page")
                self.next_turns = self.cursor("turns", result)
                self.turns = [{"id": t["id"], "status": t.get("status")} for t in rows]
                self.later(self.next_turn)
            elif kind == "items":
                rows = result.get("data")
                if (
                    not isinstance(rows, list)
                    or len(rows) > 200
                    or any(not isinstance(i, dict) for i in rows)
                ):
                    raise ValueError("invalid_item_page")
                if any(
                    row.get("turnId") != self.current_turn["id"]
                    or not isinstance(row.get("item"), dict)
                    for row in rows
                ):
                    raise ValueError("item_turn_mismatch")
                self.items = [row["item"] for row in rows]
                self.next_items = self.cursor("items", result)
                self.later(self.consume_items)
        except (ValueError, TypeError, KeyError):
            self.fail(
                "분석하지 못함 — 대화 형식 또는 페이지 순서를 확인할 수 없습니다."
            )
