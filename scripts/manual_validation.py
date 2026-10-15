"""One-hour Windows QA guide with passive measurements and explicit human evidence."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import threading
import time

from scripts.observe_process import WindowsProcess, observe, sha256


PHASES = (
    (0, 600, "초기 로딩", "펫·트레이·센터·개요·사용량 화면을 한 번씩 열어주세요."),
    (
        600,
        1200,
        "첫 조작",
        "센터 열기·닫기와 개요↔사용량 전환 10회, 펫 변경·드래그와 대화 이동을 확인하세요.",
    ),
    (
        1200,
        1800,
        "첫 대기",
        "검증 작업을 끝내고 펫 표시·센터 닫힘 상태로 대기하세요. 계정과 배율을 유지하세요.",
    ),
    (
        1800,
        2400,
        "두 번째 조작",
        "첫 조작과 같은 순서·횟수로 반복하고 Codex 작업 상태·사용량을 대조하세요.",
    ),
    (
        2400,
        3600,
        "마지막 대기",
        "첫 대기와 같은 펫·창 상태로 유지하세요. 측정이 끝날 때까지 절전하지 마세요.",
    ),
)
CHECKS = {
    "tray": "작업표시줄 트레이 우클릭·메뉴가 정상",
    "cycle1": "첫 조작 10회 완료",
    "idle1": "첫 대기는 작업 종료·펫 표시·센터 닫힘 상태 유지",
    "cycle2": "같은 조작 10회 재완료",
    "idle2": "마지막 대기도 첫 대기와 같은 상태 유지",
    "links": "A↔B 링크가 실제 원하는 대화로 이동",
    "usage": "연속 두 턴·다른 대화의 상태와 사용량 확인",
    "display": "펫 변경·드래그·모니터 이동 중 표시 이상 없음",
    "restart": "측정 후 트레이 종료·재실행과 설정 유지 확인",
}


def phase_at(elapsed):
    return next((p for p in PHASES if p[0] <= elapsed < p[1]), None)


def summarize(report):
    """Compute the predeclared idle windows; never infer human actions from memory."""
    report = Path(report)
    observation = json.loads(report.read_text(encoding="utf-8"))
    windows = [[], []]
    previous = None
    gaps = False
    with report.with_suffix(".samples.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            sample = json.loads(line)
            elapsed = sample["elapsed_seconds"]
            if previous is not None and elapsed - previous > 30:
                gaps = True
            previous = elapsed
            for index, (start, end) in enumerate(((1200, 1800), (3000, 3600))):
                if start <= elapsed < end:
                    # At most 600 records are needed, even for accidentally dense input.
                    if len(windows[index]) >= 600:
                        raise ValueError("Unexpected sample density")
                    windows[index].append(sample)
    valid = observation.get("status") == "complete" and not gaps
    results = []
    for values in windows:
        good = [
            s
            for s in values
            if s.get("memory_status") == "available"
            and type(s.get("private_bytes")) is int
        ]
        complete = (
            len(good) == len(values)
            and len(good) >= 57
            and good[-1]["elapsed_seconds"] - good[0]["elapsed_seconds"] >= 570
        )
        valid = valid and complete
        means = {}
        for key in ("private_bytes", "handle_count", "gdi_objects", "user_objects"):
            readings = [s[key] for s in good if type(s.get(key)) in (int, float)]
            means[key] = sum(readings) / len(readings) if readings else None
        results.append(
            {"samples": len(values), "valid_window": complete, "means": means}
        )
    difference = (
        results[1]["means"]["private_bytes"] - results[0]["means"]["private_bytes"]
        if valid
        else None
    )
    return {
        "observation_valid": bool(valid),
        "idle_windows": results,
        "private_difference_bytes": difference,
        "memory_target": ("passed" if difference <= 2 * 1024**2 else "needs_review")
        if valid
        else "not_assessed",
        "human_checks": "see separate user-confirmations.json",
        "overall_manual_qa": "not_automatically_assessed",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--review",
        action="store_true",
        help="Reopen a completed session and its checks",
    )
    parser.add_argument(
        "--preview",
        type=Path,
        help="Save the guide UI without starting the pet or observation",
    )
    args = parser.parse_args()
    if sha256(args.executable) != args.sha256.lower():
        parser.error("Candidate hash mismatch")
    saved_result = None
    confirmations = []
    if args.review:
        try:
            saved_result = json.loads(
                (args.output / "observation.json").read_text(encoding="utf-8")
            )
            if (
                saved_result.get("status") != "complete"
                or saved_result.get("sha256") != args.sha256.lower()
            ):
                raise ValueError("Review requires a completed matching observation")
            checks_path = args.output / "user-confirmations.json"
            if checks_path.exists():
                confirmations = json.loads(checks_path.read_text(encoding="utf-8"))
                if not isinstance(confirmations, list) or any(
                    not isinstance(item, dict)
                    or item.get("check") not in CHECKS
                    or type(item.get("confirmed")) is not bool
                    for item in confirmations
                ):
                    raise ValueError("Invalid saved checks")
        except (OSError, ValueError, AttributeError) as error:
            parser.error(str(error))
    elif args.output.exists():
        parser.error("Use a new output directory")
    else:
        args.output.mkdir(parents=True)

    from PySide6.QtCore import QObject, Signal, QTimer
    from PySide6.QtWidgets import (
        QApplication,
        QWidget,
        QVBoxLayout,
        QLabel,
        QPushButton,
        QCheckBox,
        QScrollArea,
    )

    class Signals(QObject):
        finished = Signal(object)

    class Guide(QWidget):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("펫 실사용 검수 · 60분")
            self.resize(640, 740)
            self.process = None
            self.started = None
            self.running = False
            self.closing = False
            self.cancel = threading.Event()
            self.signals = Signals(self)
            self.signals.finished.connect(self.finished)
            self.confirmations = list(confirmations)
            layout = QVBoxLayout(self)
            self.status = QLabel(
                "먼저 기존 펫 앱을 트레이에서 종료하고 검증 EXE를 열어주세요."
            )
            self.status.setWordWrap(True)
            layout.addWidget(self.status)
            self.open_button = QPushButton("1. 검증 EXE 열기")
            self.open_button.clicked.connect(self.open_candidate)
            layout.addWidget(self.open_button)
            self.ready = QCheckBox(
                "검증 펫과 트레이가 보이고 계정 A로 사용할 준비가 됐습니다"
            )
            layout.addWidget(self.ready)
            self.start_button = QPushButton("2. 60분 측정 시작")
            self.start_button.clicked.connect(self.start)
            layout.addWidget(self.start_button)
            self.clock_label = QLabel("아직 측정하지 않았습니다.")
            layout.addWidget(self.clock_label)
            self.instructions = QLabel(
                "계정 전환·Windows 배율 변경·절전 검수는 다음 세션에서 진행합니다."
            )
            self.instructions.setWordWrap(True)
            layout.addWidget(self.instructions)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            checks_widget = QWidget()
            checks_layout = QVBoxLayout(checks_widget)
            saved_checks = {
                item["check"]: item["confirmed"] for item in self.confirmations
            }
            for key, label in CHECKS.items():
                checkbox = QCheckBox(label)
                checkbox.setChecked(saved_checks.get(key, False))
                checkbox.toggled.connect(lambda value, key=key: self.mark(key, value))
                checks_layout.addWidget(checkbox)
            scroll.setWidget(checks_widget)
            layout.addWidget(scroll)
            self.stop_button = QPushButton("측정 중단 · 펫 앱은 계속 실행")
            self.stop_button.clicked.connect(self.cancel.set)
            self.stop_button.setEnabled(False)
            layout.addWidget(self.stop_button)
            self.timer = QTimer(self)
            self.timer.setInterval(1000)
            self.timer.timeout.connect(self.refresh)
            self.timer.start()
            if saved_result is not None:
                self.ready.setEnabled(False)
                self.start_button.setEnabled(False)
                self.clock_label.setText("경과 60:00 / 60:00 · 저장된 측정")
                self.finished(saved_result)

        def mark(self, key, value):
            self.confirmations.append(
                {
                    "check": key,
                    "confirmed": value,
                    "elapsed_seconds": time.monotonic() - self.started
                    if self.started
                    else None,
                    "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
                    "source": "user_reported",
                }
            )
            (args.output / "user-confirmations.json").write_text(
                json.dumps(self.confirmations, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        def open_candidate(self):
            if self.process is not None and self.process.poll() is None:
                return
            if sha256(args.executable) != args.sha256.lower():
                self.status.setText(
                    "EXE 해시가 달라 열지 않았습니다. 검사 담당자에게 알려주세요."
                )
                return
            self.process = subprocess.Popen(
                [str(args.executable.resolve())], cwd=args.executable.parent
            )
            self.status.setText(
                "펫과 트레이, 종료·재실행 후 설정 유지를 확인하고 체크해주세요."
                if args.review or self.started is not None
                else "펫과 트레이가 보이는지 확인한 뒤 준비 체크와 측정 시작을 눌러주세요."
            )

        def start(self):
            if args.review or self.running or self.started is not None:
                return
            if (
                not self.ready.isChecked()
                or self.process is None
                or self.process.poll() is not None
            ):
                self.status.setText(
                    "검증 EXE가 실행 중이어야 합니다. 기존 펫 앱을 종료하고 다시 열어주세요."
                )
                return
            try:
                target = WindowsProcess(self.process.pid, args.executable)
                if target.identity["sha256"] != args.sha256.lower():
                    target.close()
                    raise ValueError("Hash mismatch")
            except (OSError, ValueError):
                self.status.setText(
                    "대상 프로세스를 확인하지 못했습니다. 측정은 시작하지 않았습니다."
                )
                return
            self.started = time.monotonic()
            self.running = True
            self.open_button.setEnabled(False)
            self.start_button.setEnabled(False)
            self.ready.setEnabled(False)
            self.stop_button.setEnabled(True)

            def run():
                try:
                    result = observe(
                        target,
                        args.output / "observation.json",
                        3600,
                        stop_requested=self.cancel.is_set,
                    )
                    summary = summarize(args.output / "observation.json")
                    (args.output / "summary.json").write_text(
                        json.dumps(summary, indent=2), encoding="utf-8"
                    )
                except Exception as error:
                    result = {"status": "error", "issues": [type(error).__name__]}
                    (args.output / "controller-error.json").write_text(
                        json.dumps(result), encoding="utf-8"
                    )
                finally:
                    target.close()
                self.signals.finished.emit(result)

            threading.Thread(target=run, name="passive-observer").start()
            self.refresh()

        def refresh(self):
            if not self.running:
                return
            elapsed = time.monotonic() - self.started
            self.clock_label.setText(
                f"경과 {int(elapsed // 60):02d}:{int(elapsed % 60):02d} / 60:00"
            )
            phase = phase_at(elapsed)
            if phase:
                self.status.setText(phase[2])
                self.instructions.setText(phase[3])

        def finished(self, result):
            self.running = False
            self.stop_button.setEnabled(False)
            self.open_button.setEnabled(True)
            self.open_button.setText("검증 EXE 다시 열기")
            self.status.setText(
                "측정 완료"
                if result["status"] == "complete"
                else "측정 미완료 · 결과 기록됨"
            )
            self.instructions.setText(
                "측정이 끝났습니다. 트레이 종료·재실행과 설정 유지를 확인하고 체크해주세요. 펫 앱은 자동 종료하지 않습니다."
            )
            if self.closing:
                self.close()

        def closeEvent(self, event):
            if self.running:
                self.closing = True
                self.cancel.set()
                event.ignore()
            else:
                event.accept()

    app = QApplication([])
    from watched_kettle.ui.fonts import configure_application_font

    configure_application_font(app)
    window = Guide()
    window.show()
    if args.preview:
        QTimer.singleShot(
            250, lambda: (window.grab().save(str(args.preview)), window.close())
        )
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
