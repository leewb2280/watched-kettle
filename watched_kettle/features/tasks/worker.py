"""Worker-owned catalog, bounded analysis and explicit task operations."""

from dataclasses import asdict, replace
import difflib
import sqlite3

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from watched_kettle.features.tasks.catalog import ConversationCatalog
from watched_kettle.features.tasks.candidates import extract_candidates
from watched_kettle.features.tasks.connection import DesktopExecutionAdapter
from watched_kettle.features.tasks.execution import QueueExecutor
from watched_kettle.features.tasks.models import CompletionCheck, TaskSpec
from watched_kettle.features.tasks.presentation import reason_text
from watched_kettle.storage.database import DatabaseManager
from watched_kettle.storage.task_crypto import WindowsDataProtector
from watched_kettle.storage.task_repository import QueueRepository


class TaskWorker(QObject):
    snapshot = Signal(object)
    notice = Signal(str)
    comparison = Signal(str)
    approval = Signal(object)
    review_ready = Signal(object)
    task_saved = Signal(str)
    review_failed = Signal(str, str)
    save_failed = Signal(object, str)

    def __init__(self, path, factory):
        super().__init__()
        self.path, self.factory = path, factory
        self.database = None
        self.repository = None
        self.catalog = None
        self.client = None
        self.executor = None
        self.adapter = None
        self.candidates = {}
        self.versions = {}
        self.analyzed_stamps = {}
        self.analysis_status = {}
        self.read_queue = []
        self.visible_history = set()
        self.pending_review = None
        self.review_identity = ""
        self.selected_project = ""
        self.last_project = ""
        self.problem = ""
        self.account_epoch = 0
        self.timer = None
        self.read_stamp = None

    @Slot()
    def start(self):
        self.client = self.factory(parent=self)
        self.catalog = ConversationCatalog(self.client, self)
        self.catalog.changed.connect(self.catalog_changed)
        self.catalog.account_changed.connect(self.account_changed)
        self.catalog.thread_read.connect(self.analyze)
        self.catalog.failed.connect(
            lambda _reason: self.notice.emit("프로젝트·대화 목록 조회에 실패했습니다.")
        )
        self.catalog.reader.progress.connect(self.progress)
        self.catalog.reader.failed.connect(self.read_failed)
        self.adapter = DesktopExecutionAdapter(self)
        self.adapter.changed.connect(self.publish)
        self.adapter.snapshot_changed.connect(self.observe_execution)
        self.timer = QTimer(self)
        self.timer.setInterval(60_000)
        self.timer.timeout.connect(self.refresh_catalog)
        self.timer.start()
        self.publish()

    def refresh_catalog(self):
        if self.catalog and not self.catalog.reader.identity:
            self.catalog.refresh()

    def open_repository(self):
        if self.repository:
            return
        assert self.adapter is not None
        database = DatabaseManager(self.path)
        if not database.start().available:
            database.close()
            raise ValueError("task_storage_unavailable")
        try:
            self.repository = QueueRepository(database, WindowsDataProtector())
        except Exception:
            database.close()
            raise
        self.database = database
        self.executor = QueueExecutor(self.repository, self.adapter.client, self)
        self.executor.changed.connect(self.publish)
        self.executor.user_request.connect(self.approval)
        self.executor.scope_refresh_requested.connect(self.adapter.poll)

    def observe_execution(self, snapshot):
        if self.executor:
            self.executor.observe_scope(
                snapshot.scope(), observed_at=snapshot.observed_at
            )
        self.publish()

    def account_changed(self, account):
        if self.catalog is None:
            return
        self.account_epoch += 1
        self.candidates.clear()
        self.versions.clear()
        self.analyzed_stamps.clear()
        self.analysis_status.clear()
        self.read_queue.clear()
        self.visible_history.clear()
        self.pending_review = None
        self.review_identity = ""
        if self.executor:
            self.executor.connection_changed(False)
        if account:
            try:
                self.open_repository()
                assert self.repository is not None
                self.repository.set_account(str(account))
                self.repository.mark_interrupted()
                self.repository.prune()
                self.catalog.excluded_projects = set(
                    self.repository.preferences().get("excluded_projects", ())
                )
                self.problem = ""
            except (OSError, ValueError, sqlite3.Error):
                if self.repository:
                    self.repository.set_account(None)
                self.problem = (
                    "작업 저장소를 사용할 수 없습니다. 기존 데이터는 보존됩니다."
                )
        elif self.repository:
            self.repository.set_account(None)
            self.catalog.excluded_projects.clear()
        if self.adapter:
            self.adapter.set_account(
                account if self.repository and self.repository.account_key else None
            )
        self.publish()

    def recent_groups(self):
        groups: dict[str, list[str]] = {}
        if not self.catalog or self.catalog.archived:
            return groups
        for thread in sorted(
            self.catalog.threads.values(),
            key=lambda t: (t.get("updatedAt") or 0, t["id"]),
            reverse=True,
        ):
            project = thread.get("projectId") or ""
            if (
                thread.get("parentThreadId")
                or project in self.catalog.excluded_projects
            ):
                continue
            group = groups.setdefault(project, [])
            if len(group) < 10:
                group.append(thread["id"])
        return groups

    def prune_analysis(self):
        if self.catalog is None:
            return
        allowed = {i for group in self.recent_groups().values() for i in group}
        allowed.update(self.visible_history)
        if self.pending_review:
            allowed.add(self.pending_review["thread_id"])
        if self.review_identity:
            allowed.add(self.review_identity)
        for mapping in (
            self.candidates,
            self.versions,
            self.analyzed_stamps,
            self.analysis_status,
        ):
            for identity in tuple(mapping):
                thread = self.catalog.threads.get(identity)
                if (
                    identity not in allowed
                    or not thread
                    or (thread.get("projectId") or "") in self.catalog.excluded_projects
                ):
                    mapping.pop(identity, None)

    def catalog_changed(self):
        if self.catalog is None:
            return
        if not self.catalog.stale:
            self.prune_analysis()
            for identity, stamp in tuple(self.analyzed_stamps.items()):
                if self.catalog.threads.get(identity, {}).get("updatedAt") != stamp:
                    self.versions.pop(identity, None)
                    self.candidates.pop(identity, None)
                    self.analysis_status[identity] = "변경된 대화 · 다시 확인 대기"
        self.publish()
        QTimer.singleShot(0, self.analyze_next)

    def progress(self, identity, message):
        self.analysis_status[identity] = message
        self.publish()

    def read_failed(self, identity, message):
        if self.catalog is None:
            return
        self.analysis_status[identity] = message
        self.versions.pop(identity, None)
        self.candidates.pop(identity, None)
        self.analyzed_stamps[identity] = self.catalog.threads.get(identity, {}).get(
            "updatedAt"
        )
        if self.pending_review and self.pending_review["thread_id"] == identity:
            self.review_failed.emit(self.pending_review.get("token", ""), message)
            self.pending_review = None
            self.notice.emit(message)
        self.publish()
        QTimer.singleShot(0, self.analyze_next)

    def queue_read(self, identity):
        if self.catalog is None or not self.catalog.enabled or not self.catalog.account:
            raise ValueError("account_required")
        if (
            identity not in self.catalog.threads
            or (self.catalog.threads[identity].get("projectId") or "")
            in self.catalog.excluded_projects
        ):
            raise ValueError("thread_read_unavailable")
        if identity != self.catalog.reader.identity:
            if identity in self.read_queue:
                self.read_queue.remove(identity)
            self.read_queue.insert(0, identity)
        self.analysis_status[identity] = "조회 대기"
        self.analyze_next()

    def analyze_next(self):
        catalog = self.catalog
        if (
            not catalog
            or not catalog.enabled
            or not catalog.account
            or catalog.stale
            or catalog.reader.identity
        ):
            return
        identity = ""
        while self.read_queue:
            candidate = self.read_queue.pop(0)
            thread = catalog.threads.get(candidate)
            if (
                thread
                and (thread.get("projectId") or "") not in catalog.excluded_projects
            ):
                identity = candidate
                break
        if not identity:
            groups = self.recent_groups()
            projects = sorted(groups)
            if self.last_project in projects:
                offset = projects.index(self.last_project) + 1
                projects = projects[offset:] + projects[:offset]
            for project in projects:
                for candidate in groups[project]:
                    if candidate not in self.analyzed_stamps or self.analyzed_stamps[
                        candidate
                    ] != catalog.threads[candidate].get("updatedAt"):
                        identity = candidate
                        self.last_project = project
                        break
                if identity:
                    break
        if identity:
            self.read_stamp = catalog.threads[identity].get("updatedAt")
            catalog.read_thread(identity)

    def analyze(self, thread):
        if self.catalog is None:
            return
        identity = thread["id"]
        metadata = self.catalog.threads.get(identity)
        if (
            not metadata
            or (thread.get("projectId") or "") in self.catalog.excluded_projects
        ):
            QTimer.singleShot(0, self.analyze_next)
            return
        if metadata.get("updatedAt") != self.read_stamp:
            self.read_failed(identity, "대화가 갱신되어 다시 읽어야 합니다.")
            return
        result = thread.get("extraction") or extract_candidates(thread)
        self.candidates[identity] = result.candidates
        self.versions[identity] = thread["sourceVersion"]
        self.analyzed_stamps[identity] = metadata.get("updatedAt")
        self.analysis_status[identity] = (
            f"분석 완료 · 후보 {len(result.candidates)}개"
            + (" · 후보 일부만 표시" if result.truncated else "")
        )
        if self.pending_review and self.pending_review["thread_id"] == identity:
            request, self.pending_review = self.pending_review, None
            try:
                self.finish_review(request, thread, result)
            except (ValueError, TypeError, KeyError, OSError, sqlite3.Error) as error:
                self.review_failed.emit(
                    request.get("token", ""), reason_text(str(error))
                )
                self.notice.emit(reason_text(str(error)))
        self.prune_analysis()
        self.publish()
        QTimer.singleShot(0, self.analyze_next)

    def finish_review(self, request, thread, result):
        payload = {
            "token": request.get("token"),
            "thread_name": thread.get("name") or "제목 없는 대화",
            "evidence": "",
            "epoch": self.account_epoch,
        }
        if request["kind"] == "item":
            if self.repository is None:
                raise ValueError("account_required")
            item = self.repository.require(request["id"])
            if not item.spec or item.state not in {"draft", "queued"} or item.batch_id:
                raise ValueError("active_task_cannot_remove")
            spec = item.spec
            matches = [
                c
                for c in result.candidates
                if c.spec.source_candidate == spec.source_candidate
                or c.spec.title == spec.title
            ]
            current = "\n".join(c.spec.instruction for c in matches)
            if spec.source_version != thread["sourceVersion"]:
                diff = "\n".join(
                    difflib.unified_diff(
                        spec.instruction.splitlines(),
                        current.splitlines(),
                        fromfile="등록 지시문",
                        tofile="현재 해당 후보",
                        lineterm="",
                    )
                )
                payload["evidence"] = (
                    "원본 버전이 변경되었습니다. 현재 근거를 확인하고 저장하면 새 버전을 반영합니다.\n"
                    + (diff or "후보 외의 대화 내용이 변경되었습니다.")
                )
            payload.update(id=item.id, revision=item.revision)
        elif request["kind"] == "candidate":
            candidate = next(
                (
                    c
                    for c in result.candidates
                    if c.spec.source_candidate == request["candidate"]
                ),
                None,
            )
            if candidate is None:
                raise ValueError("candidate_changed")
            spec = candidate.spec
            payload["evidence"] = candidate.reason + "\n" + candidate.evidence
        else:
            spec = TaskSpec(
                "",
                "",
                thread.get("projectId") or "",
                thread["id"],
                thread.get("cwd") or "",
                "",
                checks=(CompletionCheck("작업 결과를 사용자가 확인"),),
            )
        if request.get("edits"):
            edits = TaskSpec.from_dict(request["edits"])
            spec = replace(
                spec,
                title=edits.title,
                instruction=edits.instruction,
                scope=edits.scope,
                exclusions=edits.exclusions,
                prerequisites=edits.prerequisites,
                checks=edits.checks,
                source_candidate=edits.source_candidate,
                source_refs=edits.source_refs,
            )
            payload["evidence"] = (
                "저장하지 못한 편집 내용입니다. 최신 대화와 함께 다시 검토하세요.\n"
                + payload["evidence"]
            )
        spec = replace(
            spec,
            source_version=thread["sourceVersion"],
            cwd=thread.get("cwd") or "",
            project_id=thread.get("projectId") or "",
        )
        payload["spec"] = spec.to_dict()
        self.review_identity = identity = thread["id"]
        self.versions[identity] = thread["sourceVersion"]
        self.review_ready.emit(payload)

    @Slot(str, object)
    def command(self, action, payload):
        if not self.catalog:
            return
        try:
            self._command(action, payload)
        except (
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            OSError,
            sqlite3.Error,
        ) as error:
            if action == "begin_review":
                self.pending_review = None
                self.review_failed.emit(
                    payload.get("token", ""), reason_text(str(error))
                )
            elif action == "save":
                self.save_failed.emit(payload, reason_text(str(error)))
            self.notice.emit(reason_text(str(error)))
        self.publish()

    def _command(self, action, payload):
        assert self.catalog is not None
        if action == "enable":
            self.catalog.enable(bool(payload))
        elif action == "refresh":
            self.refresh_catalog()
            self.notice.emit(
                "대화 목록을 새로 확인합니다."
                if not self.catalog.reader.identity
                else "현재 대화 분석을 마친 뒤 새로고침하세요."
            )
        elif action == "archived":
            self.catalog.reader.cancel()
            self.catalog.archived = bool(payload)
            self.candidates.clear()
            self.versions.clear()
            self.analyzed_stamps.clear()
            self.read_queue.clear()
            self.pending_review = None
            self.catalog.refresh()
        elif action == "browse":
            self.selected_project = payload.get("project") or ""
            self.visible_history = set(payload.get("history", ()))
            self.prune_analysis()
        elif action == "read":
            self.queue_read(str(payload))
        elif action == "begin_review":
            self.pending_review = dict(payload)
            self.queue_read(payload["thread_id"])
        elif action == "cancel_review":
            self.pending_review = None
            self.review_identity = ""
            self.prune_analysis()
        elif action == "exclude_project":
            project, excluded = payload
            if excluded:
                self.catalog.excluded_projects.add(project)
                if self.catalog.reader.metadata.get("projectId") == project:
                    self.catalog.reader.cancel()
                self.pending_review = None
            else:
                self.catalog.excluded_projects.discard(project)
            self.prune_analysis()
            if self.repository and self.repository.account_key:
                preferences = self.repository.preferences()
                preferences["excluded_projects"] = sorted(
                    self.catalog.excluded_projects
                )
                self.repository.save_preferences(preferences)
            self.notice.emit("프로젝트 분석 설정을 저장했습니다.")
            self.analyze_next()
        else:
            if not self.repository or not self.repository.account_key:
                raise ValueError("account_required")
            self.task_command(action, payload)

    def task_command(self, action, payload):
        if self.repository is None or self.executor is None or self.catalog is None:
            raise ValueError("account_required")
        if action == "save":
            spec = TaskSpec.from_dict(payload["spec"])
            if payload.get("epoch", self.account_epoch) != self.account_epoch:
                raise ValueError("review_version_changed")
            if payload["registered"] and (
                self.catalog.stale
                or self.versions.get(spec.thread_id) != spec.source_version
            ):
                raise ValueError("review_version_changed")
            identity = self.repository.save(
                spec,
                registered=payload["registered"],
                identity=payload.get("id", ""),
                expected_revision=payload.get("revision", 0),
            )
            self.task_saved.emit(identity)
            self.review_identity = ""
            self.notice.emit(
                "실행 대기에 등록했습니다."
                if payload["registered"]
                else "초안을 저장했습니다."
            )
        elif action == "remove":
            self.repository.remove(str(payload))
            self.notice.emit("작업을 삭제했습니다.")
        elif action == "exclude":
            self.repository.exclude(TaskSpec.from_dict(payload))
            self.notice.emit(
                "후보를 제외했습니다. 프로젝트 설정에서 복원할 수 있습니다."
            )
        elif action == "reset_exclusions":
            self.repository.reset_exclusions(payload)
            self.notice.emit("제외한 후보를 복원했습니다.")
        elif action == "reorder":
            self.repository.reorder(list(payload))
            self.notice.emit("대기 작업 순서를 변경했습니다.")
        elif action == "start_batch":
            self.executor.start_batch(
                list(payload["ids"]),
                continuous=bool(payload.get("continuous")),
                limit=int(payload.get("limit", 2)),
            )
            self.notice.emit("선택한 묶음을 시작했습니다.")
        elif action == "retry_review":
            identity = self.repository.retry_to_draft(str(payload))
            self.task_saved.emit(identity)
            self.notice.emit("재시도 초안을 만들었습니다. 원본을 검토한 뒤 등록하세요.")
        elif action == "withdraw_batch":
            self.executor.continuous_excluded.update(
                i.id
                for i in self.repository.list_items()
                if i.batch_id == str(payload)
                and i.state == "queued"
                and not i.attempt_id
            )
            self.executor.enabled_batches.discard(str(payload))
            self.repository.release_unstarted_batch(str(payload))
            self.notice.emit("선택한 묶음의 미실행 작업을 해제했습니다.")
        elif action == "answer_request":
            if payload.get("epoch") != self.executor.connection_epoch:
                raise ValueError("server_request_expired")
            self.executor.answer_request(payload["id"], payload["response"])
            self.notice.emit("답변을 보냈습니다.")
        elif action in {"pause", "resume", "emergency_stop"}:
            getattr(self.executor, action)()
            self.notice.emit(
                {
                    "pause": "전체 새 작업 배정을 일시 정지했습니다.",
                    "resume": "전체 배정을 재개했습니다.",
                    "emergency_stop": "앱이 시작한 작업의 중단을 요청했습니다.",
                }[action]
            )
        elif action in {"resume_project", "confirm_result", "reconcile", "interrupt"}:
            getattr(self.executor, action)(str(payload))
            self.notice.emit("요청을 전달했습니다. 작업 상태를 확인합니다.")
        elif action == "dismiss":
            self.repository.dismiss_terminal(str(payload))
            self.notice.emit("종료 항목을 정리했습니다.")
        else:
            raise ValueError("unknown_action")

    def publish(self):
        if not self.catalog:
            return
        try:
            items = self.repository.list_items() if self.repository else ()
            candidates = []
            if self.repository and self.repository.account_key:
                for values in self.candidates.values():
                    for candidate in values:
                        if not self.repository.excluded(candidate.spec):
                            value = asdict(candidate)
                            value["task_id"] = self.repository.candidate_task(
                                candidate.spec
                            )
                            candidates.append(value)
            self.snapshot.emit(
                {
                    "enabled": self.catalog.enabled,
                    "archived": self.catalog.archived,
                    "status": self.problem or self.catalog.status,
                    "epoch": self.account_epoch,
                    "projects": tuple(self.catalog.projects.values()),
                    "threads": tuple(self.catalog.threads.values()),
                    "candidates": candidates,
                    "items": [asdict(i) for i in items],
                    "versions": dict(self.versions),
                    "analysis_status": dict(self.analysis_status),
                    "reading": self.catalog.reader.identity,
                    "excluded_projects": tuple(self.catalog.excluded_projects),
                    "execution_available": bool(
                        self.executor
                        and self.executor.scope.reliable
                        and self.executor.clock() - self.executor.scope_at <= 3
                    ),
                    "execution_reason": self.adapter.reason
                    if self.adapter
                    else "실행 연결 준비 중",
                    "capabilities": asdict(self.adapter.capabilities)
                    if self.adapter
                    else {},
                    "wait_reasons": dict(self.executor.reasons)
                    if self.executor
                    else {},
                    "paused": self.executor.paused if self.executor else True,
                    "requests": list(self.executor.request_details.values())
                    if self.executor
                    else [],
                    "continuous_projects": tuple(self.executor.continuous_projects)
                    if self.executor
                    else (),
                }
            )
        except (OSError, ValueError, TypeError, sqlite3.Error):
            if self.executor:
                self.executor.paused = True
            self.notice.emit(
                "작업 저장소를 읽을 수 없습니다. 새 실행을 멈추고 데이터를 보존합니다."
            )

    @Slot()
    def stop(self):
        if self.timer:
            self.timer.stop()
        if self.catalog:
            self.catalog.reader.cancel()
        if self.adapter:
            self.adapter.close()
        if self.client:
            self.client.close()
        if self.database:
            self.database.close()
        self.candidates.clear()
        self.versions.clear()
