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
            accent: "#ffa21a", warn: "#ff5436", ok: "#83cf6f",
            font: "", numFont: "", numItalic: false, numWeight: Font.DemiBold,
            radius: 16, border: 1, gauge: "arc", backdrop: "grid"
        },
        // 2000s analog cluster: black faces, white ticks, orange-red needles.
        cluster: {
            bg: "#050506", panel: "#0e0f11", panelTop: "#1a1c20", panelHi: "#22252a",
            line: "#34373d", text: "#eef3f7", textDim: "#8a929b",
            accent: "#ff4f1f", warn: "#ff2a2a", ok: "#7fd4ff",
            font: "Nimbus Sans Narrow", numFont: "Nimbus Sans Narrow", numItalic: false,
            numWeight: Font.Bold,
            radius: 10, border: 1, gauge: "needle", backdrop: "dial"
        },
        // Outdoor sport-ute: olive and sand, safety orange, topo lines.
        trail: {
            bg: "#14160f", panel: "#1e2118", panelTop: "#23271c", panelHi: "#2c3123",
            line: "#4a4a35", text: "#e9dfc4", textDim: "#9c9478",
            accent: "#ff7a1a", warn: "#ff4530", ok: "#a8c66c",
            font: "URW Gothic", numFont: "URW Gothic", numItalic: false, numWeight: Font.Bold,
            radius: 6, border: 2, gauge: "segments", backdrop: "topo"
        },
        // Rally heritage: deep blue, gold, italic numerals, livery stripes.
        rally: {
            bg: "#050c1f", panel: "#0b1836", panelTop: "#12265a", panelHi: "#173070",
            line: "#21386f", text: "#f2f5ff", textDim: "#8ea0cc",
            accent: "#f2b630", warn: "#ff4d4d", ok: "#6fd3a0",
            font: "Liberation Sans Narrow", numFont: "DejaVu Sans", numItalic: true,
            numWeight: Font.Bold,
            radius: 12, border: 1, gauge: "arc", backdrop: "stripes"
        },
        // The truck's own Atlantic Blue Pearl: deep navy, steel-blue accent.
        atlantic: {
            bg: "#0a1420", panel: "#101f33", panelTop: "#162a45", panelHi: "#1d3558",
            line: "#2d4a73", text: "#eaf1fb", textDim: "#93a9c8",
            accent: "#5b8fd0", warn: "#ff5a47", ok: "#6fd3a0",
            font: "", numFont: "", numItalic: false, numWeight: Font.DemiBold,
            radius: 14, border: 1, gauge: "arc", backdrop: "waves"
        },
        // Night driving: pure black so the window and rail go flat, with no
        // backdrop to glow. Text is deliberately not full white, and the
        // accent is a muted cool teal that doesn't bloom on an 8 inch panel.
        midnight: {
            bg: "#000000", panel: "#08090b", panelTop: "#0e1013", panelHi: "#16191d",
            line: "#272b31", text: "#d6dae0", textDim: "#8a919b",
            accent: "#4fb8cc", warn: "#ff5436", ok: "#7cc47a",
            font: "", numFont: "", numItalic: false, numWeight: Font.DemiBold,
            radius: 12, border: 1, gauge: "arc", backdrop: "none"
        },
        // Desert: sand and terracotta-brown, with turquoise as the accent. The
        // turquoise sits well away from the red-orange warning colour.
        desert: {
            bg: "#18120c", panel: "#251c13", panelTop: "#2c2218", panelHi: "#37291c",
            line: "#5a4631", text: "#f1e3c8", textDim: "#b19c7c",
            accent: "#3fc1b0", warn: "#ff5a36", ok: "#b6c96a",
            font: "", numFont: "Nimbus Sans", numItalic: false, numWeight: Font.Bold,
            radius: 8, border: 2, gauge: "arc", backdrop: "topo"
        },
        // Glacier: ice cyan on deep teal-black. The roundest look, with
        // generous corners and a cool, crisp accent that reads well at night.
        glacier: {
            bg: "#071216", panel: "#0e2027", panelTop: "#132932", panelHi: "#1a3540",
            line: "#2f5663", text: "#e8f6f9", textDim: "#8fb2bd",
            accent: "#7fe0f0", warn: "#ff5f4d", ok: "#8fe0a8",
            font: "", numFont: "", numItalic: false, numWeight: Font.DemiBold,
            radius: 20, border: 1, gauge: "arc", backdrop: "dial"
        },
        // LCD: retro green monochrome, like an 80s dashboard display. Phosphor
        // green text on near-black, with segment gauges and a mono numeral
        // face. Warnings stay orange-red so they still stand out.
        lcd: {
            bg: "#050b05", panel: "#0b160a", panelTop: "#0f1d0e", panelHi: "#16270f",
            line: "#2c4a22", text: "#b9f27a", textDim: "#7fae5a",
            accent: "#e4ff5a", warn: "#ff6a3d", ok: "#5fe08e",
            font: "", numFont: "DejaVu Sans Mono", numItalic: false, numWeight: Font.Bold,
            radius: 2, border: 2, gauge: "segments", backdrop: "grid"
        },
        // Sunset: deep purple at night with a gold accent. The gold sits far
        // from the pink-red warning colour, so an alert is never read as a
        // selected state.
        sunset: {
            bg: "#140a1f", panel: "#21122f", panelTop: "#2c1840", panelHi: "#3a2154",
            line: "#5a3a7a", text: "#fbeef2", textDim: "#b79bc4",
            accent: "#ffb347", warn: "#ff4d6d", ok: "#7fe0b0",
            font: "", numFont: "", numItalic: false, numWeight: Font.DemiBold,
            radius: 18, border: 1, gauge: "arc", backdrop: "grid"
        }
    })
    // The same looks for daylight: light grounds, dark text, the accents
    // deepened a little so they hold up on a light background.
    readonly property var lightStyles: ({
        amber: {
            bg: "#ece9e3", panel: "#f8f6f2", panelTop: "#fbfaf7", panelHi: "#e4e0d7",
            line: "#cdc6ba", text: "#1d1b18", textDim: "#68625a",
            accent: "#c06a00", warn: "#cc3418", ok: "#3c8a2b"
        },
        cluster: {
            bg: "#e8eaed", panel: "#f7f8fa", panelTop: "#ffffff", panelHi: "#e0e3e8",
            line: "#c5cad2", text: "#13171c", textDim: "#5b636d",
            accent: "#c93a10", warn: "#cf1f1f", ok: "#1e7db5"
        },
        trail: {
            bg: "#e8e3d4", panel: "#f6f2e7", panelTop: "#fbf8f0", panelHi: "#e5dfcc",
            line: "#c8bfa4", text: "#23261b", textDim: "#696450",
            accent: "#c4560a", warn: "#c4321f", ok: "#4c7c29"
        },
        rally: {
            bg: "#e2e7f2", panel: "#f5f7fc", panelTop: "#ffffff", panelHi: "#dbe2f1",
            line: "#b8c3dc", text: "#0b1633", textDim: "#4d5d84",
            accent: "#a86e00", warn: "#d03030", ok: "#1d875a"
        },
        atlantic: {
            bg: "#e4eaf3", panel: "#f5f8fc", panelTop: "#ffffff", panelHi: "#d9e2f0",
            line: "#b5c4dc", text: "#0c1a30", textDim: "#4a5d7c",
            accent: "#2a5fa8", warn: "#c92f2f", ok: "#1c8456"
        },
        // Midnight by day: white sheets, near-black text, the teal deepened
        // so it holds on a light ground.
        midnight: {
            bg: "#f0f1f2", panel: "#ffffff", panelTop: "#ffffff", panelHi: "#e3e5e8",
            line: "#c4c8ce", text: "#0a0b0d", textDim: "#555b64",
            accent: "#0a7388", warn: "#c8321a", ok: "#2f7d2c"
        },
        // Desert by day: sand paper and dark brown text, with the turquoise
        // deepened to hold on the light ground.
        desert: {
            bg: "#eadfc6", panel: "#f8f1e1", panelTop: "#fcf8ee", panelHi: "#e2d5b6",
            line: "#cbb994", text: "#2a2014", textDim: "#6d5d44",
            accent: "#0b766a", warn: "#c4321f", ok: "#5a7a1e"
        },
        // Glacier by day: a bright near-white ground with cool blue-grey
        // panels, and the cyan deepened so it holds on the light ground.
        glacier: {
            bg: "#e3eef2", panel: "#f6fafb", panelTop: "#ffffff", panelHi: "#d7e6ec",
            line: "#b4cbd4", text: "#0b1d24", textDim: "#476470",
            accent: "#0a6f8c", warn: "#c8321f", ok: "#22804a"
        },
        // LCD by day: a grey-green calculator panel with dark green ink.
        lcd: {
            bg: "#c3cea4", panel: "#d3dcb8", panelTop: "#dde5c6", panelHi: "#b5c295",
            line: "#8fa072", text: "#16210c", textDim: "#3f4f2a",
            accent: "#2f5a0f", warn: "#a8260f", ok: "#1f6b2e"
        },
        // Sunset by day: soft pink-white sheets with plum text, and the gold
        // deepened to a burnt amber so it holds on the light ground.
        sunset: {
            bg: "#f3e6ea", panel: "#fcf6f7", panelTop: "#ffffff", panelHi: "#ebdbe2",
            line: "#d3b9c6", text: "#2a1230", textDim: "#6e4f76",
            accent: "#b4540a", warn: "#c4203f", ok: "#1f7d57"
        }
    })
    readonly property var styleNames: ["amber", "cluster", "trail", "rally", "atlantic", "midnight", "desert", "glacier", "lcd", "sunset"]
    // Display names, since charAt(0).toUpperCase() would get "LCD" wrong.
    readonly property var styleTitles: ({ amber: "Amber", cluster: "Cluster", trail: "Trail",
                                          rally: "Rally", atlantic: "Atlantic", midnight: "Midnight",
                                          desert: "Desert", glacier: "Glacier", lcd: "LCD",
                                          sunset: "Sunset" })
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
    readonly property string backdrop: s.backdrop  // "none", "topo", "stripes", "grid", "dial", "waves" or "dunes"

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
