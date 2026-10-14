import QtQuick

// A labelled switch-panel key ("Pair phone", "Join", "Restart"). `primary`
// is the screen's main action (accent fill); `danger` marks one that can't
// be undone. Disabled keys fade to half strength.
Rectangle {
    id: btn
    property string text
    property string icon: ""
    property bool primary: false
    property bool danger: false
    signal clicked()

    implicitWidth: row.implicitWidth + 40
    implicitHeight: 56
    radius: Theme.radius
    border.width: Theme.border
    border.color: primary ? Theme.accent : (danger ? Qt.rgba(Theme.warn.r, Theme.warn.g, Theme.warn.b, 0.6) : Theme.line)
    color: primary ? (tap.pressed ? Qt.darker(Theme.accent, 1.25) : Theme.accent)
                   : (tap.pressed ? Theme.line : Theme.panelHi)
    opacity: enabled ? 1 : 0.5
    scale: tap.pressed ? 0.97 : 1
    Behavior on scale { NumberAnimation { duration: 70 } }

    Row {
        id: row
        anchors.centerIn: parent
        spacing: 10
        Icon {
            visible: btn.icon !== ""
            anchors.verticalCenter: parent.verticalCenter
            name: btn.icon
            size: 24
            color: label.color
        }
        Label {
            id: label
            anchors.verticalCenter: parent.verticalCenter
            text: btn.text
            color: btn.primary ? Theme.bg : (btn.danger ? Theme.warn : Theme.text)
            font.pixelSize: Theme.fontBody - 2
            font.weight: Font.DemiBold
        }
    }

    TapHandler { id: tap; onTapped: btn.clicked() }
}
