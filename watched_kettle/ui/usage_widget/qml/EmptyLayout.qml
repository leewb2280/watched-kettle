// Shown when no provider has anything to report yet.
import QtQuick
import "WidgetStyle.js" as Style

Item {
    implicitWidth: Math.ceil(label.implicitWidth) + px(28)
    implicitHeight: Math.ceil(label.implicitHeight) + px(20)

    function px(value) { return Style.px(value, widgetModel.scale) }

    Text {
        id: label
        anchors.centerIn: parent
        text: "연결된 사용량이 없습니다"
        color: widgetModel.theme.float_muted
        font.pixelSize: parent.px(11)
        style: widgetModel.theme.halo ? Text.Outline : Text.Normal
        styleColor: widgetModel.theme.halo_color
    }
}
