// Layout A: one row per provider with a large number and a bar for its
// tighter or chosen limit; the other limit sits underneath in small text.
import QtQuick
import "WidgetStyle.js" as Style

Item {
    id: layout
    readonly property var theme: widgetModel.theme
    implicitWidth: px(252)
    implicitHeight: rows.implicitHeight + px(20)

    function px(value) { return Style.px(value, widgetModel.scale) }

    Column {
        id: rows
        x: layout.px(12)
        y: layout.px(10)
        width: parent.width - layout.px(24)
        spacing: layout.px(8)

        Repeater {
            model: widgetModel.state.providers

            Column {
                id: row
                required property var modelData
                required property int index
                readonly property var provider: modelData
                readonly property bool limited: Style.hasLimit(provider)
                readonly property color levelColor: Style.valueColor(layout.theme, provider)
                width: rows.width
                spacing: layout.px(4)

                Rectangle {
                    visible: row.index > 0
                    width: parent.width
                    height: 1
                    color: layout.theme.float_line
                }

                Row {
                    id: header
                    width: parent.width
                    spacing: layout.px(6)
                    Rectangle {
                        id: dot
                        width: layout.px(7); height: width; radius: width / 2
                        anchors.verticalCenter: parent.verticalCenter
                        color: Style.sourceColor(layout.theme, row.provider.key)
                    }
                    Text {
                        width: parent.width - dot.width - badges.width - header.spacing * 2
                        text: row.provider.name
                        color: layout.theme.float_ink
                        font.pixelSize: layout.px(12)
                        style: widgetModel.theme.halo ? Text.Outline : Text.Normal
                        styleColor: widgetModel.theme.halo_color
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                    }
                    StatusBadges {
                        id: badges
                        provider: row.provider
                        theme: layout.theme
                    }
                }

                Text {
                    visible: !row.limited
                    text: Style.stateText(row.provider)
                    color: layout.theme.float_muted
                    font.pixelSize: layout.px(11)
                    style: widgetModel.theme.halo ? Text.Outline : Text.Normal
                    styleColor: widgetModel.theme.halo_color
                }

                Column {
                    visible: row.limited
                    width: parent.width
                    spacing: layout.px(4)

                    Row {
                        spacing: layout.px(6)
                        Text {
                            text: row.limited ? Style.valueText(row.provider.main) : ""
                            color: row.levelColor
                            font.pixelSize: layout.px(19)
                            style: widgetModel.theme.halo ? Text.Outline : Text.Normal
                            styleColor: widgetModel.theme.halo_color
                            font.weight: Font.Bold
                        }
                        Text {
                            anchors.baseline: parent.children[0].baseline
                            text: row.limited
                                ? row.provider.main.labelRemainingText
                                  + (row.provider.main.resetText ? " · " + row.provider.main.resetText : "")
                                : ""
                            color: layout.theme.float_muted
                            font.pixelSize: layout.px(11)
                            style: widgetModel.theme.halo ? Text.Outline : Text.Normal
                            styleColor: widgetModel.theme.halo_color
                        }
                    }

                    Rectangle {
                        width: parent.width
                        height: layout.px(5)
                        radius: height / 2
                        color: Qt.alpha(layout.theme.float_muted, 0.2)
                        Rectangle {
                            width: row.limited ? Math.round(parent.width * row.provider.main.remaining / 100) : 0
                            height: parent.height
                            radius: height / 2
                            color: row.levelColor
                        }
                    }

                    Text {
                        width: parent.width
                        text: {
                            const p = row.provider
                            let line = p.other ? p.other.remainingText : ""
                            if (p.state === "stale" && p.age)
                                line += (line ? " · " : "") + p.sampleText
                            return line
                        }
                        visible: text !== ""
                        color: layout.theme.float_muted
                        font.pixelSize: layout.px(11)
                        style: widgetModel.theme.halo ? Text.Outline : Text.Normal
                        styleColor: widgetModel.theme.halo_color
                    }
                }

                TodayStrip {
                    width: parent.width
                    provider: row.provider
                    theme: layout.theme
                }
            }
        }
    }
}
