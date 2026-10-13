pragma Singleton
import QtQuick

// One place for colors and sizes. Amber accent matches the planned
// amber-backlit climate buttons and volume knob halo on the faceplate.
QtObject {
    readonly property color bg: "#0a0a0c"
    readonly property color panel: "#151518"
    readonly property color panelHi: "#1f1f24"
    readonly property color line: "#2c2c33"
    readonly property color text: "#f3efe8"
    readonly property color textDim: "#8f8b84"
    readonly property color accent: "#ffa21a"
    readonly property color accentDim: "#5c3d0d"
    readonly property color warn: "#ff5436"
    readonly property color ok: "#83cf6f"

    readonly property int radius: 16
    readonly property int gap: 14
    readonly property int touch: 76   // minimum tap target, ~15 mm on this panel

    // Big, legible type for arm's-length reading in daylight.
    readonly property int fontSmall: 16
    readonly property int fontBody: 22
    readonly property int fontTitle: 30
    readonly property int fontHuge: 64
}
