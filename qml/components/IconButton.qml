import QtQuick

// Round touch button for transport controls (prev / play / next).
Rectangle {
    id: btn
    property string glyph
    property bool primary: false
    property int size: Theme.touch
    signal clicked()

    width: size
    height: size
    radius: size / 2
    color: primary ? (tap.pressed ? Qt.darker(Theme.accent, 1.3) : Theme.accent)
                   : (tap.pressed ? Theme.line : Theme.panelHi)

    Text {
        anchors.centerIn: parent
        text: btn.glyph
        font.pixelSize: btn.size * 0.38
        color: btn.primary ? Theme.bg : Theme.text
    }

    TapHandler {
        id: tap
        onTapped: btn.clicked()
    }
}
