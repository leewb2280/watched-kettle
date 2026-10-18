// Layout B (default): one ring per provider for its tighter or chosen limit.
// Running and attention counts sit as a badge on the ring's corner.
import QtQuick
import QtQuick.Shapes
import "WidgetStyle.js" as Style

Item {
    id: layout
    readonly property var theme: widgetModel.theme
    implicitWidth: row.implicitWidth + px(24)
    implicitHeight: row.implicitHeight + px(20)

    function px(value) { return Style.px(value, widgetModel.scale) }

    Row {
        id: row
        x: layout.px(12)
        y: layout.px(10)
        spacing: layout.px(10)

        Repeater {
            model: widgetModel.state.providers

            Column {
                id: cell
                required property var modelData
                readonly property var provider: modelData
                readonly property bool limited: Style.hasLimit(provider)
                readonly property color levelColor: Style.valueColor(layout.theme, provider)
                width: layout.px(104)
                spacing: layout.px(3)

                Item {
                    id: ring
                    readonly property int stroke: layout.px(6)
                    readonly property real radius: (width - stroke) / 2 - layout.px(1)
                    width: layout.px(58)
                    height: width
                    anchors.horizontalCenter: parent.horizontalCenter

                    Shape {
                        anchors.fill: parent
                        preferredRendererType: Shape.CurveRenderer
                        ShapePath {
                            strokeColor: Qt.alpha(layout.theme.float_muted, 0.22)
                            strokeWidth: ring.stroke
                            fillColor: "transparent"
                            PathAngleArc {
                                centerX: ring.width / 2; centerY: ring.height / 2
                                radiusX: ring.radius; radiusY: ring.radius
                                startAngle: -90; sweepAngle: 360
                            }
                        }
                        ShapePath {
                            strokeColor: cell.levelColor
                            strokeWidth: ring.stroke
                            fillColor: "transparent"
                            capStyle: ShapePath.RoundCap
                            PathAngleArc {
                                centerX: ring.width / 2; centerY: ring.height / 2
                                radiusX: ring.radius; radiusY: ring.radius
                                startAngle: -90
                                sweepAngle: cell.limited ? 3.6 * cell.provider.main.remaining : 0
                            }
                        }
                    }

                    Text {
                        anchors.centerIn: parent
                        text: cell.limited ? Style.valueText(cell.provider.main)
                            : cell.provider.state === "offline" ? "!" : "–"
                        color: cell.levelColor
                        font.pixelSize: layout.px(14)
                        style: widgetModel.theme.halo ? Text.Outline : Text.Normal
                        styleColor: widgetModel.theme.halo_color
                        font.weight: Font.Bold
                    }

                    // Attention wins over running: it is what needs the user.
                    Rectangle {
                        readonly property int count: cell.provider.attention || cell.provider.running
                        visible: count > 0
                        x: parent.width - width + layout.px(6)
                        y: -layout.px(3)
                        width: Math.max(height, Math.ceil(countText.implicitWidth) + layout.px(8))
                        height: layout.px(17)
                        radius: height / 2
                        color: cell.provider.attention ? layout.theme.status_attention
                                                       : layout.theme.status_running
                        Text {
                            id: countText
                            anchors.centerIn: parent
                            text: parent.count
                            color: layout.theme.float_card
                            font.pixelSize: layout.px(10)
                            style: widgetModel.theme.halo ? Text.Outline : Text.Normal
                            styleColor: widgetModel.theme.halo_color
                            font.weight: Font.Bold
                        }
                    }
                }

                Row {
                    anchors.horizontalCenter: parent.horizontalCenter
                    spacing: layout.px(5)
                    Rectangle {
                        width: layout.px(7); height: width; radius: width / 2
                        anchors.verticalCenter: parent.verticalCenter
                        color: Style.sourceColor(layout.theme, cell.provider.key)
                    }
                    Text {
                        text: cell.provider.name
                        color: layout.theme.float_ink
                        font.pixelSize: layout.px(11)
                        style: widgetModel.theme.halo ? Text.Outline : Text.Normal
                        styleColor: widgetModel.theme.halo_color
                        font.weight: Font.DemiBold
                    }
                }

                Text {
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.WordWrap
                    color: layout.theme.float_muted
                    font.pixelSize: layout.px(10)
                    style: widgetModel.theme.halo ? Text.Outline : Text.Normal
                    styleColor: widgetModel.theme.halo_color
                    lineHeight: 1.15
                    text: {
                        const p = cell.provider
                        if (!cell.limited)
                            return Style.stateText(p)
                        let first = Style.labelText(p.main) + (p.main.resetText ? " · " + p.main.resetText : "")
                        let second = p.other ? p.other.remainingText : ""
                        if (p.state === "stale" && p.age)
                            second += (second ? " · " : "") + p.sampleText
                        return second ? first + "\n" + second : first
                    }
                }

                TodayStrip {
                    width: parent.width
                    provider: cell.provider
                    theme: layout.theme
                }
            }
        }
    }
}
