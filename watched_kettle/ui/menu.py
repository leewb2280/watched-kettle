from dataclasses import dataclass
from typing import Any

from PySide6.QtGui import QActionGroup
from PySide6.QtWidgets import QMenu


@dataclass(frozen=True)
class PetMenuCommand:
    name: str
    value: Any = None


def show_pet_context_menu(
    parent,
    global_position,
    current_state,
    idle_activities_enabled,
    auto_movement_enabled,
    always_on_top,
    usage_widget_available=False,
    usage_widget_visible=False,
    usage_widget_shape="rings",
    usage_widget_tasks_visible=True,
    usage_widget_today_visible=False,
    usage_widget_position_customized=False,
    menu_executor=None,
):
    menu = QMenu(parent)

    status_action = menu.addAction(f"현재 상태: {current_state or 'idle'}")
    status_action.setEnabled(False)
    menu.addSeparator()

    idle_activity_action = menu.addAction("자동 행동")
    idle_activity_action.setCheckable(True)
    idle_activity_action.setChecked(idle_activities_enabled)

    auto_movement_action = menu.addAction("자동 이동")
    auto_movement_action.setCheckable(True)
    auto_movement_action.setChecked(auto_movement_enabled)

    always_on_top_action = menu.addAction("항상 위")
    always_on_top_action.setCheckable(True)
    always_on_top_action.setChecked(always_on_top)

    usage_menu = menu.addMenu("사용량 위젯")
    usage_menu.setEnabled(usage_widget_available)
    usage_menu.menuAction().setVisible(usage_widget_available)
    usage_widget_action = usage_menu.addAction("위젯 표시")
    usage_widget_action.setCheckable(True)
    usage_widget_action.setChecked(usage_widget_visible)
    usage_widget_action.setEnabled(usage_widget_available)
    usage_menu.addSeparator()
    shape_group = QActionGroup(usage_menu)
    shape_group.setExclusive(True)
    shape_actions = {}
    for key, label in (
        ("rings", "링"),
        ("bars", "두 줄 막대"),
        ("chips", "작은 칩"),
    ):
        action = usage_menu.addAction(label)
        action.setCheckable(True)
        action.setChecked(usage_widget_shape == key)
        action.setEnabled(usage_widget_available)
        shape_group.addAction(action)
        shape_actions[action] = key
    usage_menu.addSeparator()
    tasks_action = usage_menu.addAction("작업 상태 표시")
    tasks_action.setCheckable(True)
    tasks_action.setChecked(usage_widget_tasks_visible)
    tasks_action.setEnabled(usage_widget_available)
    today_action = usage_menu.addAction("오늘 흐름 표시")
    today_action.setCheckable(True)
    today_action.setChecked(usage_widget_today_visible)
    today_action.setEnabled(usage_widget_available)

    usage_menu.addSeparator()
    usage_settings_action = usage_menu.addAction("위젯 설정 열기")
    usage_settings_action.setEnabled(usage_widget_available)
    reset_usage_widget_action = usage_menu.addAction("펫 옆에 다시 붙이기")
    reset_usage_widget_action.setEnabled(
        usage_widget_available and usage_widget_position_customized
    )

    menu.addSeparator()

    settings_action = menu.addAction("설정")
    recenter_action = menu.addAction("화면 중앙으로 불러오기")

    menu.addSeparator()
    quit_action = menu.addAction("종료")

    selected = (
        menu_executor(menu, global_position)
        if menu_executor is not None
        else menu.exec(global_position)
    )

    if selected == idle_activity_action:
        return PetMenuCommand(
            "set_idle_activities_enabled",
            idle_activity_action.isChecked(),
        )
    if selected == auto_movement_action:
        return PetMenuCommand(
            "set_auto_movement_enabled",
            auto_movement_action.isChecked(),
        )
    if selected == always_on_top_action:
        return PetMenuCommand(
            "set_always_on_top",
            always_on_top_action.isChecked(),
        )
    if selected == usage_widget_action:
        return PetMenuCommand(
            "set_usage_widget_visible",
            usage_widget_action.isChecked(),
        )
    if selected in shape_actions:
        return PetMenuCommand("set_usage_widget_shape", shape_actions[selected])
    if selected == tasks_action:
        return PetMenuCommand(
            "set_usage_widget_tasks_visible", tasks_action.isChecked()
        )
    if selected == today_action:
        return PetMenuCommand(
            "set_usage_widget_today_visible", today_action.isChecked()
        )
    if selected == usage_settings_action:
        return PetMenuCommand("show_usage_settings")
    if selected == reset_usage_widget_action:
        return PetMenuCommand("reset_usage_widget_position")
    if selected == settings_action:
        return PetMenuCommand("show_settings")
    if selected == recenter_action:
        return PetMenuCommand("recenter")
    if selected == quit_action:
        return PetMenuCommand("quit")

    return None
