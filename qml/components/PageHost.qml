import QtQuick

// Holds one page and animates it in and out: a short crossfade with a
// slight slide toward the direction you navigated. Hidden pages are made
// invisible once faded, so they cost nothing to draw (the 3D page included).
Item {
    id: host
    property int index
    property int current
    default property alias content: holder.data
    readonly property bool shown: current === index

    opacity: shown ? 1 : 0
    visible: opacity > 0
    Behavior on opacity { NumberAnimation { duration: 240; easing.type: Easing.OutCubic } }

    Item {
        id: holder
        width: parent.width
        height: parent.height
        x: host.shown ? 0 : (host.index < host.current ? -40 : 40)
        Behavior on x { NumberAnimation { duration: 240; easing.type: Easing.OutCubic } }
    }
}
