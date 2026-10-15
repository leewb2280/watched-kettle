"""Capture the real Qt assistant stack without touching user preferences."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtCore import QPoint, QSettings
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from watched_kettle.pet.window import DesktopPet
from watched_kettle.state.presentation import BubbleNotice, PresentationUpdate


@dataclass(frozen=True)
class AssistantPreviewCapture:
    output_path: Path
    bubble_count: int
    bubble_widths: tuple[int, ...]
    primary_tail_side: str | None
    width: int
    height: int
    screen_name: str
    work_area: tuple[int, int, int, int]
    widget_rects: tuple[tuple[int, int, int, int], ...]
    all_widgets_in_work_area: bool


def capture_assistant_preview(
    output_path,
    pet_directory,
    screen_index=0,
    placement="center",
    scale_percent=100,
):
    output_path = Path(output_path).resolve()
    pet_directory = Path(pet_directory)
    app = QApplication.instance() or QApplication([])

    with TemporaryDirectory() as temporary_directory:
        settings = QSettings(
            str(Path(temporary_directory) / "preview.ini"),
            QSettings.Format.IniFormat,
        )
        settings.setValue("bubbleScalePercent", int(scale_percent))
        pet = DesktopPet(pet_directory, settings=settings)
        try:
            screens = QApplication.screens()
            if not 0 <= screen_index < len(screens):
                raise IndexError(
                    f"screen_index {screen_index} is outside "
                    f"the {len(screens)} available screens"
                )
            screen = screens[screen_index]
            if screen is not None:
                work_area = screen.availableGeometry()
                center = work_area.center()
                x = center.x() - pet.width() // 2
                y = center.y() - pet.height() // 2 + 120
                if placement == "top":
                    y = work_area.top()
                elif placement == "right":
                    x = work_area.right() - pet.width() + 1
                elif placement != "center":
                    raise ValueError(f"unknown placement: {placement}")
                pet.move(x, y)
            pet.show()

            waiting = BubbleNotice(
                message="확인이 필요한 작업이 있어요",
                source="codex",
                event="waiting",
                session_id="preview-waiting",
                kind="waiting",
                priority=80,
                replace_key="preview:waiting",
            )
            error = BubbleNotice(
                message=(
                    "Codex 작업 하나에서 문제가 생겼어요. "
                    "자세한 내용은 작업 화면에서 확인해 주세요"
                ),
                source="codex",
                event="failed",
                session_id="preview-error",
                duration_ms=60_000,
                kind="error",
                priority=100,
                replace_key="preview:error",
            )
            done = BubbleNotice(
                message="Codex 작업 2개를 완료했어요",
                source="codex",
                event="done",
                session_id="preview-done",
                duration_ms=60_000,
                kind="done",
                priority=40,
                replace_key="preview:done",
                count=2,
                member_ids=("preview-one", "preview-two"),
            )
            pet.bubble_controller.apply(
                PresentationUpdate(
                    state="waiting",
                    notice=error,
                    persistent_notices=(waiting,),
                )
            )
            pet.bubble_controller.apply(
                PresentationUpdate(
                    state="waiting",
                    notice=done,
                    persistent_notices=(waiting,),
                )
            )
            for _ in range(5):
                app.processEvents()

            bubbles = pet.bubble_controller.visible_windows
            widgets = (pet, *bubbles)
            rectangles = [widget.frameGeometry() for widget in widgets]
            work_area = screen.availableGeometry()
            padding = 16
            left = min(rect.left() for rect in rectangles) - padding
            top = min(rect.top() for rect in rectangles) - padding
            right = max(rect.right() for rect in rectangles) + padding
            bottom = max(rect.bottom() for rect in rectangles) + padding
            image = QImage(
                right - left + 1,
                bottom - top + 1,
                QImage.Format.Format_ARGB32_Premultiplied,
            )
            image.fill(QColor("#ece8e1"))
            painter = QPainter(image)
            try:
                origin = QPoint(left, top)
                for widget in widgets:
                    painter.drawPixmap(
                        widget.frameGeometry().topLeft() - origin,
                        widget.grab(),
                    )
            finally:
                painter.end()

            output_path.parent.mkdir(parents=True, exist_ok=True)
            if not image.save(str(output_path)):
                raise OSError(f"미리보기 이미지를 저장할 수 없습니다: {output_path}")
            return AssistantPreviewCapture(
                output_path=output_path,
                bubble_count=len(bubbles),
                bubble_widths=tuple(bubble.width() for bubble in bubbles),
                primary_tail_side=(bubbles[0].tail_side if bubbles else None),
                width=image.width(),
                height=image.height(),
                screen_name=screen.name(),
                work_area=work_area.getRect(),
                widget_rects=tuple(rect.getRect() for rect in rectangles),
                all_widgets_in_work_area=all(
                    work_area.contains(rect) for rect in rectangles
                ),
            )
        finally:
            pet.close()
            app.processEvents()


def main():
    output_path = Path(
        sys.argv[1]
        if len(sys.argv) > 1
        else Path(__file__).resolve().parents[1]
        / "dev-artifacts"
        / "previews"
        / "assistant-native-preview.png"
    )
    pet_directory = Path(sys.argv[2] if len(sys.argv) > 2 else "pets/mori-bot")
    screen_index = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    placement = sys.argv[4] if len(sys.argv) > 4 else "center"
    scale_percent = int(sys.argv[5]) if len(sys.argv) > 5 else 100
    result = capture_assistant_preview(
        output_path,
        pet_directory,
        screen_index=screen_index,
        placement=placement,
        scale_percent=scale_percent,
    )
    print(
        f"Captured {result.bubble_count} bubbles at "
        f"{result.width}x{result.height}; widths={result.bubble_widths}; "
        f"tail={result.primary_tail_side}; screen={result.screen_name}; "
        f"in_bounds={result.all_widgets_in_work_area}: "
        f"{result.output_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
