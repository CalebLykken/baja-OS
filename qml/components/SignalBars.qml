import QtQuick

// Wi-Fi strength as four rising bars, lit from the left like the level bars.
Row {
    id: bars
    property int signal: 0          // 0-100, as NetworkManager reports it
    property color lit: Theme.text
    // Zero means no reading (a garbled or vanished network), so no bar is lit.
    readonly property int count: signal >= 75 ? 4 : signal >= 50 ? 3 : signal >= 25 ? 2 : signal > 0 ? 1 : 0
    spacing: 3
    height: 22
    // Width comes from the bars: 4 * 6 + 3 * 3 = 33 px.

    Repeater {
        model: 4
        Rectangle {
            anchors.bottom: parent.bottom
            width: 6
            // Whole pixels, so each step is crisp on the Pi's panel.
            height: Math.round(bars.height * (index + 1) / 4)
            radius: 0
            color: index < bars.count ? bars.lit : Theme.line
        }
    }
}
