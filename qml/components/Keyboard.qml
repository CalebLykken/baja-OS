import QtQuick

// On-screen keyboard for the few things typed on the dashboard, like a
// Wi-Fi password. Same keys as the rest of the panel: shift gives one
// capital (tap it twice for caps lock), "123" switches to numbers and
// symbols, and holding delete keeps deleting.
Rectangle {
    id: kb
    signal typed(string ch)
    signal backspace()
    signal done()
    property string doneLabel: "Done"
    property bool doneEnabled: true

    property int shift: 0               // 0 off, 1 next letter, 2 caps lock
    property int mode: 0                // 0 letters, 1 numbers, 2 more symbols

    readonly property var layers: [
        [["q","w","e","r","t","y","u","i","o","p"], ["a","s","d","f","g","h","j","k","l"], ["z","x","c","v","b","n","m"]],
        [["1","2","3","4","5","6","7","8","9","0"], ["-","/",":",";","(",")","$","&","@","\""], [".",",","?","!","'"]],
        [["[","]","{","}","#","%","^","*","+","="], ["_","\\","|","~","<",">","€","£","¥","•"], [".",",","?","!","'"]]
    ]
    readonly property var rows: layers[mode]
    readonly property real gap: 8
    readonly property real keyW: (width - 24 - 9 * gap) / 10
    readonly property real keyH: (height - 24 - 3 * gap) / 4

    color: Theme.panel
    radius: Theme.radius
    border.width: Theme.border
    border.color: Theme.line

    function shown(ch) { return kb.mode === 0 && kb.shift > 0 ? ch.toUpperCase() : ch }
    function press(ch) {
        kb.typed(shown(ch))
        if (kb.shift === 1) kb.shift = 0
    }

    // The character key under the finger, if any; its label shows in the bubble.
    property var previewKey: null
    onVisibleChanged: if (!visible) previewKey = null

    component Key: Rectangle {
        id: key
        property string label
        property string icon: ""
        property bool primary: false
        property bool lit: false
        property bool preview: false     // character keys pop up a bubble while held
        readonly property alias down: area.pressed
        signal hit()
        width: kb.keyW
        height: kb.keyH
        radius: Theme.radius
        border.width: Theme.border
        border.color: primary ? Theme.accent : Theme.line
        color: primary ? (area.pressed ? Qt.darker(Theme.accent, 1.25) : Theme.accent)
                       : (area.pressed ? Theme.line : (lit ? Theme.line : Theme.panelHi))
        opacity: enabled ? 1 : 0.5
        scale: area.pressed ? 0.96 : 1
        // Press dips in 70 ms, release springs back in 180 ms (OutBack). The
        // same numbers are used in Card, TextButton, IconButton, NavButton,
        // Keyboard and SegmentedControl. Runs only on a touch, so there is no
        // idle cost.
        Behavior on scale { id: pressSpring; NumberAnimation { duration: pressSpring.targetValue < 1 ? 70 : 180; easing.type: pressSpring.targetValue < 1 ? Easing.OutQuad : Easing.OutBack; easing.overshoot: 2.5 } }
        onDownChanged: {
            if (key.preview) {
                if (key.down) kb.previewKey = key
                else if (kb.previewKey === key) kb.previewKey = null
            }
        }
        Label {
            visible: key.icon === ""
            anchors.centerIn: parent
            text: key.label
            color: key.primary ? Theme.bg : Theme.text
            font.pixelSize: key.label.length > 1 ? Theme.fontBody - 2 : Theme.fontTitle
            font.weight: key.primary ? Font.DemiBold : Font.Normal
        }
        Icon {
            visible: key.icon !== ""
            anchors.centerIn: parent
            name: key.icon
            size: 30
            color: key.lit ? Theme.accent : Theme.text
        }
        MouseArea { id: area; anchors.fill: parent; onClicked: key.hit() }
    }

    // Swallow taps in the gaps and frame so they don't reach what's under
    // the keyboard (the keys' own MouseAreas sit above this one).
    MouseArea { anchors.fill: parent }

    Column {
        anchors { fill: parent; margins: 12 }
        spacing: kb.gap

        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: kb.gap
            Repeater { model: kb.rows[0]; Key { preview: true; label: kb.shown(modelData); onHit: kb.press(modelData) } }
        }
        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: kb.gap
            Repeater { model: kb.rows[1]; Key { preview: true; label: kb.shown(modelData); onHit: kb.press(modelData) } }
        }
        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: kb.gap
            Key {
                width: kb.keyW * 1.5
                icon: kb.mode === 0 ? "shift" : ""
                label: kb.mode === 1 ? "#+=" : "123"
                lit: kb.mode === 0 && kb.shift > 0
                onHit: {
                    if (kb.mode === 0) kb.shift = kb.shift === 0 ? 1 : (kb.shift === 1 ? 2 : 0)
                    else kb.mode = kb.mode === 1 ? 2 : 1
                }
            }
            Repeater { model: kb.rows[2]; Key { preview: true; label: kb.shown(modelData); onHit: kb.press(modelData) } }
            Key {
                id: del
                width: kb.keyW * 1.5
                icon: "backspace"
                onHit: kb.backspace()
                // Hold to keep deleting, after a short pause.
                Timer {
                    property int ticks: 0
                    running: del.down
                    interval: 110; repeat: true
                    onRunningChanged: ticks = 0
                    onTriggered: if (++ticks > 3) kb.backspace()
                }
            }
        }
        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: kb.gap
            Key {
                width: kb.keyW * 1.5
                label: kb.mode === 0 ? "123" : "ABC"
                onHit: kb.mode = kb.mode === 0 ? 1 : 0
            }
            Key {
                width: kb.keyW * 5.5 + kb.gap * 4
                label: "space"
                onHit: kb.typed(" ")
            }
            Key {
                width: kb.keyW * 2.5 + kb.gap
                label: kb.doneLabel
                primary: true
                enabled: kb.doneEnabled
                onHit: kb.done()
            }
        }
    }

    // One shared bubble for every character key, not one per key. It sits
    // above the held key and is not clipped, so top-row keys can overhang.
    Rectangle {
        id: bubble
        z: 10
        visible: kb.previewKey !== null
        width: kb.keyW * 1.4
        height: kb.keyH * 1.3
        radius: Theme.radius
        color: Theme.panelHi
        border.width: 2
        border.color: Theme.accent
        x: kb.previewKey ? Math.max(0, Math.min(kb.width - width,
               kb.previewKey.mapToItem(kb, 0, 0).x + (kb.previewKey.width - width) / 2)) : 0
        y: kb.previewKey ? kb.previewKey.mapToItem(kb, 0, 0).y - height - 4 : 0
        scale: visible ? 1 : 0.8
        Behavior on scale { NumberAnimation { duration: 80 } }
        Label {
            anchors.centerIn: parent
            text: kb.previewKey ? kb.previewKey.label : ""
            font.pixelSize: Theme.fontHero
        }
    }
}
