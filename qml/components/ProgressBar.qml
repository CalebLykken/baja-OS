import QtQuick

// Thin bar for track progress, volume, and similar 0..1 values.
Rectangle {
    property real value: 0
    property color fill: Theme.accent

    height: 6
    radius: 3
    color: Theme.line

    Rectangle {
        width: parent.width * Math.max(0, Math.min(1, parent.value))
        height: parent.height
        radius: parent.radius
        color: parent.fill
    }
}
