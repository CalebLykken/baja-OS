pragma Singleton
import QtQuick

// One place for colors, fonts and sizes. `style` picks a set of tokens from
// `styles`; everything else binds to the active set, so switching style at
// runtime restyles the whole UI.
QtObject {
    id: theme

    property string style: "trail"     // the default look

    readonly property var styles: ({
        // The original look: near-black panels, amber accent.
        amber: {
            bg: "#0a0a0c", panel: "#151518", panelTop: "#151518", panelHi: "#1f1f24",
            line: "#2c2c33", text: "#f3efe8", textDim: "#8f8b84",
            accent: "#ffa21a", accentDim: "#5c3d0d", warn: "#ff5436", ok: "#83cf6f",
            font: "", numFont: "", numItalic: false, numWeight: Font.DemiBold,
            radius: 16, border: 1, gauge: "arc", backdrop: "none"
        },
        // 2000s analog cluster: black faces, white ticks, orange-red needles.
        cluster: {
            bg: "#050506", panel: "#0e0f11", panelTop: "#1a1c20", panelHi: "#22252a",
            line: "#34373d", text: "#eef3f7", textDim: "#8a929b",
            accent: "#ff4f1f", accentDim: "#4a1a0c", warn: "#ff2a2a", ok: "#7fd4ff",
            font: "Nimbus Sans Narrow", numFont: "Nimbus Sans Narrow", numItalic: false,
            numWeight: Font.Bold,
            radius: 10, border: 1, gauge: "needle", backdrop: "none"
        },
        // Outdoor sport-ute: olive and sand, safety orange, topo lines.
        trail: {
            bg: "#14160f", panel: "#1e2118", panelTop: "#23271c", panelHi: "#2c3123",
            line: "#4a4a35", text: "#e9dfc4", textDim: "#9c9478",
            accent: "#ff7a1a", accentDim: "#4d2a0e", warn: "#ff4530", ok: "#a8c66c",
            font: "URW Gothic", numFont: "URW Gothic", numItalic: false, numWeight: Font.Bold,
            radius: 6, border: 2, gauge: "segments", backdrop: "topo"
        },
        // Rally heritage: deep blue, gold, italic numerals, livery stripes.
        rally: {
            bg: "#050c1f", panel: "#0b1836", panelTop: "#12265a", panelHi: "#173070",
            line: "#21386f", text: "#f2f5ff", textDim: "#8ea0cc",
            accent: "#f2b630", accentDim: "#4a3a10", warn: "#ff4d4d", ok: "#6fd3a0",
            font: "Liberation Sans Narrow", numFont: "DejaVu Sans", numItalic: true,
            numWeight: Font.Bold,
            radius: 12, border: 1, gauge: "arc", backdrop: "stripes"
        }
    })
    readonly property var styleNames: ["amber", "cluster", "trail", "rally"]
    readonly property var s: styles[style] || styles.amber

    readonly property color bg: s.bg
    readonly property color panel: s.panel
    readonly property color panelTop: s.panelTop   // top of the panel gradient
    readonly property color panelHi: s.panelHi
    readonly property color line: s.line
    readonly property color text: s.text
    readonly property color textDim: s.textDim
    readonly property color accent: s.accent
    readonly property color accentDim: s.accentDim
    readonly property color warn: s.warn
    readonly property color ok: s.ok

    // Empty family means the platform default (DejaVu Sans on the Pi).
    readonly property string font: s.font
    readonly property string numFont: s.numFont
    readonly property bool numItalic: s.numItalic
    readonly property int numWeight: s.numWeight

    readonly property int radius: s.radius
    readonly property int border: s.border
    readonly property string gauge: s.gauge        // "arc", "needle" or "segments"
    readonly property string backdrop: s.backdrop  // "none", "topo" or "stripes"

    readonly property int gap: 14
    readonly property int touch: 76   // minimum tap target, ~15 mm on this panel

    // Big, legible type for arm's-length reading in daylight.
    readonly property int fontSmall: 16
    readonly property int fontBody: 22
    readonly property int fontTitle: 30
    readonly property int fontHuge: 64
}
