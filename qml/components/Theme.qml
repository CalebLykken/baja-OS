pragma Singleton
import QtQuick

// One place for colors, fonts and sizes. `style` picks a set of tokens from
// `styles` (or `lightStyles` when `dark` is off, by day); everything else
// binds to the active set, so switching style or day/night at runtime
// restyles the whole UI.
QtObject {
    id: theme

    property string style: "trail"     // the default look
    property bool dark: true           // Main.qml: light by day, dark at night

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
    // The same looks for daylight: light grounds, dark text, the accents
    // deepened a little so they hold up on a light background.
    readonly property var lightStyles: ({
        amber: {
            bg: "#ece9e3", panel: "#f8f6f2", panelTop: "#fbfaf7", panelHi: "#e4e0d7",
            line: "#cdc6ba", text: "#1d1b18", textDim: "#68625a",
            accent: "#d27c00", accentDim: "#f3dfb9", warn: "#cc3418", ok: "#3c8a2b"
        },
        cluster: {
            bg: "#e8eaed", panel: "#f7f8fa", panelTop: "#ffffff", panelHi: "#e0e3e8",
            line: "#c5cad2", text: "#13171c", textDim: "#5b636d",
            accent: "#de4316", accentDim: "#f7cdbd", warn: "#cf1f1f", ok: "#1e7db5"
        },
        trail: {
            bg: "#e8e3d4", panel: "#f6f2e7", panelTop: "#fbf8f0", panelHi: "#e5dfcc",
            line: "#c8bfa4", text: "#23261b", textDim: "#696450",
            accent: "#e2650c", accentDim: "#f5d2b5", warn: "#c4321f", ok: "#4c7c29"
        },
        rally: {
            bg: "#e2e7f2", panel: "#f5f7fc", panelTop: "#ffffff", panelHi: "#dbe2f1",
            line: "#b8c3dc", text: "#0b1633", textDim: "#4d5d84",
            accent: "#c48600", accentDim: "#f2e1ae", warn: "#d03030", ok: "#1d875a"
        }
    })
    readonly property var styleNames: ["amber", "cluster", "trail", "rally"]
    readonly property var base: styles[style] || styles.amber
    // Colours from the day or night set; fonts and shapes always from base.
    readonly property var s: dark ? base : Object.assign({}, base, lightStyles[style] || {})

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

    readonly property string mapFont: "Overpass"     // the map, its labels and its controls

    readonly property int gap: 14
    readonly property int touch: 100  // minimum tap target, ~13 mm on this panel

    // Type scale (docs/DESIGN.md), sized to read from the driver's seat
    // (70-90 cm) on this 189 ppi panel: body text is about 12-16 arc
    // minutes there (ISO 15008's floor is 12'). Nothing else should invent
    // a size.
    readonly property int fontLegend: 20      // instrument legends: caps, DemiBold, tracked
    readonly property real legendTracking: 2
    readonly property int fontSmall: 24       // times, units, secondary lines
    readonly property int fontBody: 30        // artists, list rows, settings text
    readonly property int fontTitle: 40       // page and card titles, track titles
    readonly property int fontHero: 56        // place names (Maps), the Baja OS title in Settings
    readonly property int fontReadout: 56     // readout numerals
    readonly property int fontHuge: 88        // distance to the next turn
}
