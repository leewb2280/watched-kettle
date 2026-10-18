// Today's tokens for one provider: a total and one bar per shown hour.
// Unobserved hours draw a faint stub so they never read as zero.
import QtQuick
import "WidgetStyle.js" as Style

Column {
    id: strip
    required property var provider
    required property var theme
    readonly property var flow: provider.today
    visible: flow !== undefined && flow !== null
    spacing: px(2)

    function px(value) { return Style.px(value, widgetModel.scale) }

    Row {
        width: parent.width
        Text {
            width: parent.width - total.width
            text: widgetModel.labels.today
            color: strip.theme.float_muted
            font.pixelSize: strip.px(10)
            style: widgetModel.theme.halo ? Text.Outline : Text.Normal
            styleColor: widgetModel.theme.halo_color
        }
        Text {
            id: total
            text: strip.flow ? strip.flow.total : ""
            color: strip.theme.float_ink
            font.pixelSize: strip.px(10)
            style: widgetModel.theme.halo ? Text.Outline : Text.Normal
            styleColor: widgetModel.theme.halo_color
            font.weight: Font.DemiBold
        }
    }

    Item {
        id: bars
        width: parent.width
        height: strip.px(16)
        readonly property int count: strip.flow ? strip.flow.bars.length : 0
        readonly property real slot: count > 0 ? width / count : 0

        Repeater {
            model: strip.flow ? strip.flow.bars : []
            Rectangle {
                required property var modelData
                required property int index
                readonly property bool observed: modelData >= 0
                // Whole-pixel edges so neighbouring bars keep an even gap.
                x: Math.round(index * bars.slot)
                width: Math.max(1, Math.round((index + 1) * bars.slot) - x - 1)
                height: observed ? Math.max(1, Math.round(modelData * bars.height)) : strip.px(2)
                y: bars.height - height
                radius: 1
                color: Style.sourceColor(strip.theme, strip.provider.key)
                opacity: observed ? 0.85 : 0.25
            }
        }
    }
}
