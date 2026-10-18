// "확인 N" and "작업 N" pills for one provider; empty when nothing runs.
import QtQuick
import "WidgetStyle.js" as Style

Row {
    id: badges
    required property var provider
    required property var theme
    spacing: px(4)

    function px(value) { return Style.px(value, widgetModel.scale) }

    Repeater {
        model: [
            { count: badges.provider.attention, label: widgetModel.labels.attention, color: badges.theme.status_attention },
            { count: badges.provider.running, label: widgetModel.labels.running, color: badges.theme.status_running }
        ]
        Rectangle {
            required property var modelData
            visible: modelData.count > 0
            width: visible ? Math.ceil(text.implicitWidth) + badges.px(12) : 0
            height: badges.px(17)
            radius: height / 2
            color: Qt.alpha(modelData.color, 0.16)
            Text {
                id: text
                anchors.centerIn: parent
                text: parent.modelData.label + " " + parent.modelData.count
                color: parent.modelData.color
                font.pixelSize: badges.px(11)
                style: widgetModel.theme.halo ? Text.Outline : Text.Normal
                styleColor: widgetModel.theme.halo_color
                font.weight: Font.DemiBold
            }
        }
    }
}
