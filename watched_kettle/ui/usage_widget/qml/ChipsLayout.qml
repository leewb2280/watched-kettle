// Layout C: one quiet chip per provider. Hovering the widget unfolds the
// reset time, the other limit and the task counts under each chip.
import QtQuick
import QtQuick.Shapes
import "WidgetStyle.js" as Style

Item {
    id: layout
    readonly property var theme: widgetModel.theme
    readonly property bool expanded: hover.hovered || widgetModel.expanded
    // Where the name, today's strip and the unfolded lines start.
    readonly property int textStart: px(38)
    implicitWidth: px(214)
    implicitHeight: chips.implicitHeight + px(12)

    function px(value) { return Style.px(value, widgetModel.scale) }

    HoverHandler { id: hover }

    Column {
        id: chips
        x: layout.px(6)
        y: layout.px(6)
        width: parent.width - layout.px(12)
        spacing: layout.px(4)

        Repeater {
            model: widgetModel.state.providers

            Column {
                id: chip
                required property var modelData
                readonly property var provider: modelData
                readonly property bool limited: Style.hasLimit(provider)
                readonly property color levelColor: Style.valueColor(layout.theme, provider)
                width: chips.width

                Item {
                    width: parent.width
                    height: layout.px(34)

                    Shape {
                        id: mini
                        readonly property int stroke: layout.px(4)
                        readonly property real radius: (width - stroke) / 2 - layout.px(1)
                        x: layout.px(8)
                        anchors.verticalCenter: parent.verticalCenter
                        width: layout.px(22)
                        height: width
                        visible: chip.limited
                        preferredRendererType: Shape.CurveRenderer
                        ShapePath {
                            strokeColor: Qt.alpha(layout.theme.float_muted, 0.22)
                            strokeWidth: mini.stroke
                            fillColor: "transparent"
                            PathAngleArc {
                                centerX: mini.width / 2; centerY: mini.height / 2
                                radiusX: mini.radius; radiusY: mini.radius
                                startAngle: -90; sweepAngle: 360
                            }
                        }
                        ShapePath {
                            strokeColor: chip.levelColor
                            strokeWidth: mini.stroke
                            fillColor: "transparent"
                            capStyle: ShapePath.RoundCap
                            PathAngleArc {
                                centerX: mini.width / 2; centerY: mini.height / 2
                                radiusX: mini.radius; radiusY: mini.radius
                                startAngle: -90
                                sweepAngle: chip.limited ? 3.6 * chip.provider.main.remaining : 0
                            }
                        }
                    }
                    Rectangle {
                        visible: !chip.limited
                        x: mini.x + (mini.width - width) / 2
                        anchors.verticalCenter: parent.verticalCenter
                        width: layout.px(8); height: width; radius: width / 2
                        color: Style.sourceColor(layout.theme, chip.provider.key)
                    }

                    Text {
                        id: name
                        x: layout.textStart
                        anchors.verticalCenter: parent.verticalCenter
                        width: parent.width - x - trailing.width - layout.px(10)
                        text: chip.provider.name
                        color: Style.sourceColor(layout.theme, chip.provider.key)
                        font.pixelSize: layout.px(12)
                        style: widgetModel.theme.halo ? Text.Outline : Text.Normal
                        styleColor: widgetModel.theme.halo_color
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                    }

                    Row {
                        id: trailing
                        anchors.right: parent.right
                        anchors.rightMargin: layout.px(8)
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: layout.px(6)
                        Rectangle {
                            readonly property int count: chip.provider.attention || chip.provider.running
                            visible: count > 0
                            anchors.verticalCenter: parent.verticalCenter
                            width: layout.px(7); height: width; radius: width / 2
                            color: chip.provider.attention ? layout.theme.status_attention
                                                           : layout.theme.status_running
                        }
                        Text {
                            text: chip.limited ? Style.valueText(chip.provider.main) : Style.stateText(chip.provider)
                            color: chip.limited ? chip.levelColor : layout.theme.float_muted
                            font.pixelSize: layout.px(chip.limited ? 14 : 11)
                            style: widgetModel.theme.halo ? Text.Outline : Text.Normal
                            styleColor: widgetModel.theme.halo_color
                            font.weight: chip.limited ? Font.Bold : Font.Normal
                        }
                        Text {
                            visible: chip.limited
                            anchors.baseline: parent.children[1].baseline
                            text: chip.limited ? Style.labelText(chip.provider.main) : ""
                            color: layout.theme.float_muted
                            font.pixelSize: layout.px(11)
                            style: widgetModel.theme.halo ? Text.Outline : Text.Normal
                            styleColor: widgetModel.theme.halo_color
                        }
                    }
                }

                TodayStrip {
                    x: layout.textStart
                    width: chip.width - layout.textStart - layout.px(8)
                    bottomPadding: layout.px(4)
                    provider: chip.provider
                    theme: layout.theme
                }

                Column {
                    visible: layout.expanded && chip.limited
                    x: layout.textStart
                    bottomPadding: layout.px(6)
                    spacing: layout.px(2)
                    Repeater {
                        model: {
                            const p = chip.provider
                            if (!chip.limited)
                                return []
                            // The chip already shows the main percent and window.
                            const lines = p.main.reset ? [p.main.reset + " 초기화"] : []
                            if (p.other)
                                lines.push(p.other.label + " 남음 " + Style.percentText(p.other))
                            const tasks = [p.running ? "작업 중 " + p.running : "",
                                           p.attention ? "확인 필요 " + p.attention : ""].filter(Boolean)
                            if (tasks.length)
                                lines.push(tasks.join(" · "))
                            if (p.state === "stale" && p.age)
                                lines.push(p.age + " 값")
                            return lines
                        }
                        Text {
                            required property var modelData
                            width: chip.width - layout.textStart - layout.px(8)
                            text: modelData
                            color: layout.theme.float_muted
                            font.pixelSize: layout.px(11)
                            style: widgetModel.theme.halo ? Text.Outline : Text.Normal
                            styleColor: widgetModel.theme.halo_color
                            elide: Text.ElideRight
                        }
                    }
                }
            }
        }
    }
}
