import QtQuick

// Wi-Fi strength as four rising bars, lit from the left like the level bars.
Row {
    id: bars
    property int signal: 0          // 0-100, as NetworkManager reports it
    property color lit: Theme.text
    readonly property int count: signal >= 75 ? 4 : signal >= 50 ? 3 : signal >= 25 ? 2 : 1
    spacing: 3
    height: 22

    Repeater {
        model: 4
        Rectangle {
            anchors.bottom: parent.bottom
            width: 5
            height: bars.height * (index + 1) / 4
            radius: 1
            color: index < bars.count ? bars.lit : Theme.line
        }
    }
}
