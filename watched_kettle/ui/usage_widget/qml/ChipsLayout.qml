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

    // Share the trailing slot so proportional digits and translated window
    // labels cannot move one provider's activity dot sideways.
    FontMetrics {
        id: valueMetrics
        font.pixelSize: layout.px(14)
        font.weight: Font.Bold
    }
    FontMetrics {
        id: labelMetrics
        font.pixelSize: layout.px(11)
    }
    readonly property real limitSummaryWidth: {
        let widest = 0
        const providers = widgetModel.state.providers
        for (let i = 0; i < providers.length; ++i) {
            if (Style.hasLimit(providers[i]))
                widest = Math.max(widest,
                    valueMetrics.advanceWidth(Style.valueText(providers[i].main))
                    + labelMetrics.advanceWidth(Style.labelText(providers[i].main)))
        }
        return Math.ceil(widest) + px(6)
            + (widgetModel.state.tasksVisible ? px(7) + px(6) : 0)
    }

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
                        width: chip.limited ? layout.limitSummaryWidth : implicitWidth
                        anchors.right: parent.right
                        anchors.rightMargin: layout.px(8)
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: layout.px(6)
                        Rectangle {
                            objectName: "activityDot_" + chip.provider.key
                            visible: widgetModel.state.tasksVisible
                            anchors.verticalCenter: parent.verticalCenter
                            width: layout.px(7); height: width; radius: width / 2
                            color: chip.provider.attention ? layout.theme.status_attention
                                : chip.provider.running ? layout.theme.status_running
                                                        : layout.theme.float_muted
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
                    visible: layout.expanded
                    x: layout.textStart
                    bottomPadding: layout.px(6)
                    spacing: layout.px(2)
                    Repeater {
                        model: {
                            const p = chip.provider
                            // Limit details and activity are independent inputs.
                            const lines = chip.limited && p.main.resetText ? [p.main.resetText] : []
                            if (p.other)
                                lines.push(p.other.remainingText)
                            if (widgetModel.state.tasksVisible) {
                                const tasks = [p.running ? p.workingText : "",
                                               p.attention ? p.attentionText : ""].filter(Boolean)
                                lines.push(tasks.length ? tasks.join(" · ") : p.noTasksText)
                            }
                            if (p.state === "stale" && p.age)
                                lines.push(p.sampleText)
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
                            wrapMode: Text.WordWrap
                        }
                    }
                }
            }
        }
    }
}
