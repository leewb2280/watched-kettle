"""Synthetic task service shared by task notification and discovery tests."""

from PySide6.QtCore import QObject, Signal

from watched_kettle.features.tasks.models import CheckKind, CompletionCheck, TaskSpec


class PreviewTaskService(QObject):
    changed = Signal()
    notice = Signal(str)
    comparison = Signal(str)
    approval = Signal(object)
    review_ready = Signal(object)
    review_failed = Signal(str, str)
    task_saved = Signal(str)
    save_failed = Signal(object, str)

    def __init__(self):
        super().__init__()
        self.calls = []
        self.spec = TaskSpec(
            "위젯 표시 오류 수정",
            "사용량 위젯의 표시 오류를 수정하고 관련 테스트를 실행하세요.",
            "sample-project",
            "sample-thread",
            "C:/example/project",
            "sample-version",
            scope="위젯 표시 로직과 관련 테스트",
            exclusions="실행 파일 배포",
            checks=(
                CompletionCheck(
                    "관련 테스트 통과", CheckKind.COMMAND, "python -m unittest"
                ),
            ),
            source_candidate="위젯 표시 오류 수정",
        )
        self.state = {
            "epoch": 1,
            "enabled": True,
            "status": "프로젝트 1개 · 대화 1개 · 최근 대화의 명시적 계획 분석",
            "projects": [{"id": "sample-project", "name": "예시 프로젝트"}],
            "threads": [
                {
                    "id": "sample-thread",
                    "projectId": "sample-project",
                    "name": "사용량 위젯 개선",
                    "cwd": "C:/example/project",
                    "status": {"type": "idle"},
                }
            ],
            "candidates": [
                {
                    "spec": self.spec.to_dict(),
                    "reason": "사용자의 명시적 계획",
                    "evidence": "- [ ] 위젯 표시 오류 수정",
                    "confirmed_plan": True,
                }
            ],
            "items": [
                {
                    "id": "sample-task",
                    "state": "draft",
                    "revision": 1,
                    "spec": self.spec.to_dict(),
                    "reason": "",
                    "batch_id": "",
                    "attempt_id": "",
                }
            ],
            "versions": {"sample-thread": "sample-version"},
            "execution_available": False,
            "execution_reason": "Desktop 전체 실행 상태와 승인 연결의 호환성 검증이 필요합니다.",
        }

    def send(self, action, payload=None):
        self.calls.append((action, payload))
