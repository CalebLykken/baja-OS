import QtQuick

// Page backdrop made from the current album art: the pre-blurred cover
// (~24 px, scaled up smoothly so it reads as a heavy blur at no GPU cost),
// darkened so cards and text stay legible. Fades in and out with the music.
Item {
    id: root
    property real strength: 0.55                     // how much art shows through
    readonly property bool active: media.artBlur !== ""

    Image {
        anchors.fill: parent
        source: media.artBlur
        fillMode: Image.PreserveAspectCrop
        smooth: true
        opacity: root.active ? root.strength : 0
        Behavior on opacity { NumberAnimation { duration: 600 } }
    }
    Rectangle {
        anchors.fill: parent
        color: Theme.bg
        opacity: root.active ? 0.5 : 0
        Behavior on opacity { NumberAnimation { duration: 600 } }
    }
}
