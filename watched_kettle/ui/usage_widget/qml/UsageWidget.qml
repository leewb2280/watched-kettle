// Root of the usage widget: one card that loads the chosen layout.
// The window sizes itself to this item (SizeViewToRootObject).
//
// The layouts apply the size setting to their own lengths (WidgetStyle.px)
// instead of this item scaling them: the software scene graph draws a
// rounded Rectangle at its own size and then stretches it, so a 1.3x
// Item.scale left stepped corners, a jagged badge circle and a 1px border
// of uneven width (2026-10-05).
import QtQuick

Item {
    id: root
    readonly property var theme: widgetModel.theme
    // Acrylic (glass) covers the whole window and DWM rounds its corners, so
    // the card drops its own shadow, border and larger radius.
    readonly property bool glass: theme.glass === true
    // One device pixel per shadow ring, whatever the widget size.
    readonly property int shadowRings: glass ? 0 : 3
    width: card.width + shadowRings * 2
    height: card.height + shadowRings * 2

    // A soft edge from rounds that each sit one pixel further out than the
    // last; the software scene graph has no blur effects. They stay outside
    // the card so a see-through card does not show them through itself.
    Repeater {
        model: root.shadowRings
        Rectangle {
            readonly property int step: index + 1
            x: card.x - step
            y: card.y - step
            width: card.width + step * 2
            height: card.height + step * 2
            radius: card.radius + step
            color: "transparent"
            border.width: 1
            border.color: root.theme.float_shadow
            opacity: 0.45 - index * 0.13
        }
    }

    Rectangle {
        id: card
        x: root.shadowRings
        y: root.shadowRings
        width: loader.item ? Math.ceil(loader.item.implicitWidth) : 120
        height: loader.item ? Math.ceil(loader.item.implicitHeight) : 40
        // DWM rounds the acrylic window by its own 8px, whatever the size.
        radius: root.glass ? 8 : Math.round(12 * widgetModel.scale)
        color: root.theme.float_surface
        border.width: root.glass ? 0 : 1
        border.color: root.theme.float_line

        Loader {
            id: loader
            anchors.fill: parent
            source: widgetModel.state.empty
                ? "EmptyLayout.qml"
                : ({ bars: "BarsLayout.qml", rings: "RingsLayout.qml", chips: "ChipsLayout.qml" })[widgetModel.layout]
                    || "RingsLayout.qml"
        }
    }
}
