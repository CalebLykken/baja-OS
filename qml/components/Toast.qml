import QtQuick

// A transient message pill: slides in, holds, fades out, all from one
// SequentialAnimation that ends by itself. Not drawn while hidden, and it has
// no tap handler, so it never takes a tap. The owner places it (anchors) and
// decides when a message is allowed; a second show() while one is up just
// replaces the text and restarts the hold, there is no queue.
Rectangle {
    id: toast
    property string text: ""
    property string icon: ""
    property int holdMs: 4000
    // The widest the pill gets. Names from another device (a phone's name,
    // a place) are longer than this sometimes: the text elides instead.
    readonly property int maxWidth: 520

    width: Math.min(maxWidth, row.implicitWidth + 56)
    height: row.implicitHeight + 24
    radius: Theme.radius
    color: Theme.panel
    border { width: Theme.border; color: Theme.line }
    opacity: 0
    visible: opacity > 0

    function show(message, iconName) {
        text = message
        icon = iconName || ""
        showAnim.restart()
    }

    function hide() {
        showAnim.stop()
        opacity = 0
    }

    Row {
        id: row
        anchors.centerIn: parent
        spacing: 12

        Icon {
            id: toastIcon
            visible: toast.icon !== ""
            anchors.verticalCenter: parent.verticalCenter
            name: toast.icon
            size: Theme.fontBody + 6
            color: Theme.text
        }
        Label {
            anchors.verticalCenter: parent.verticalCenter
            // What's left of the pill after the padding and the icon, so a long
            // name elides with "..." and the pill stays within maxWidth.
            width: Math.min(implicitWidth, toast.maxWidth - 56
                            - (toastIcon.visible ? toastIcon.width + row.spacing : 0))
            elide: Text.ElideRight
            text: toast.text
            color: Theme.text
            font.pixelSize: Theme.fontBody
            font.weight: Font.DemiBold
        }
    }

    transform: Translate { id: slide; y: 0 }

    SequentialAnimation {
        id: showAnim
        ParallelAnimation {
            NumberAnimation { target: toast; property: "opacity"; to: 1; duration: 250; easing.type: Easing.OutCubic }
            NumberAnimation { target: slide; property: "y"; from: -20; to: 0; duration: 250; easing.type: Easing.OutCubic }
        }
        PauseAnimation { duration: toast.holdMs }
        NumberAnimation { target: toast; property: "opacity"; to: 0; duration: 400 }
    }
}
