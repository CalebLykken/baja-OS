import QtQuick
import QtQuick.Layouts
import "../components"

// Settings. Brightness drives the panel; units and about are placeholders.
Item {
    id: page
    signal navigate(int index)

    // Saved between runs; QSettings hands booleans back as strings.
    property bool metric: typeof settings !== "undefined"
                          && String(settings.get("metric", "false")) === "true"
    onMetricChanged: if (typeof settings !== "undefined") settings.set("metric", metric ? "true" : "false")

    ColumnLayout {
        anchors.fill: parent
        spacing: Theme.gap

        Card {
            Layout.fillWidth: true
            Layout.preferredHeight: 120
            heading: display.hardware ? "Brightness" : "Brightness (software dim)"

            RowLayout {
                anchors { fill: parent; leftMargin: 20; rightMargin: 20; topMargin: 36 }
                spacing: 16
                IconButton { icon: "remove"; size: 60; onClicked: display.setBrightness(display.brightness - 10) }

                LevelBar {
                    Layout.fillWidth: true
                    value: display.brightness / 100
                    onMoved: (v) => display.setBrightness(Math.round(v * 100))
                }
                Label {
                    Layout.preferredWidth: 64
                    horizontalAlignment: Text.AlignRight
                    text: display.brightness + "%"
                    font.family: Theme.numFont
                    font.pixelSize: Theme.fontBody
                    font.weight: Font.DemiBold
                }
                IconButton { icon: "add"; size: 60; onClicked: display.setBrightness(display.brightness + 10) }
            }
        }

        // Style and units share a row to leave room for Bluetooth.
        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 120
            Layout.fillHeight: false   // the cards inside fill it; it mustn't grow
            spacing: Theme.gap

            Card {
                Layout.fillWidth: true
                Layout.fillHeight: true
                heading: "Style"

                SegmentedControl {
                    anchors { left: parent.left; leftMargin: 20; verticalCenter: parent.verticalCenter; verticalCenterOffset: 14 }
                    options: Theme.styleNames.map(n => ({ label: n.charAt(0).toUpperCase() + n.slice(1), value: n }))
                    current: Theme.style
                    onPicked: (v) => Theme.style = v
                }
            }

            Card {
                Layout.fillWidth: true
                Layout.fillHeight: true
                heading: "Units"

                SegmentedControl {
                    anchors { left: parent.left; leftMargin: 20; verticalCenter: parent.verticalCenter; verticalCenterOffset: 14 }
                    options: [{ label: "mph, °F", value: false }, { label: "km/h, °C", value: true }]
                    current: page.metric
                    onPicked: (v) => page.metric = v
                }
            }
        }

        Card {
            id: btCard
            Layout.fillWidth: true
            Layout.preferredHeight: 120
            heading: "Bluetooth"
            visible: typeof bluetooth !== "undefined" && bluetooth.available

            property int secondsLeft: 0
            Timer {
                interval: 1000; repeat: true; triggeredOnStart: true
                running: btCard.visible && bluetooth.pairing
                onTriggered: btCard.secondsLeft = bluetooth.pairingSecondsLeft
            }
            function mmss(s) { return Math.floor(s / 60) + ":" + (s % 60 < 10 ? "0" : "") + s % 60 }

            Row {
                anchors { left: parent.left; leftMargin: 20; verticalCenter: parent.verticalCenter; verticalCenterOffset: 14 }
                spacing: 14
                Icon {
                    anchors.verticalCenter: parent.verticalCenter
                    name: "bluetooth"
                    size: 30
                    color: bluetooth.deviceName !== "" || bluetooth.pairing ? Theme.accent : Theme.textDim
                }
                Label {
                    anchors.verticalCenter: parent.verticalCenter
                    font.pixelSize: Theme.fontBody
                    text: !bluetooth.adapterPresent ? "Bluetooth is off"
                          : bluetooth.pairing ? "Visible as “Baja OS”: pair from your phone (" + btCard.mmss(btCard.secondsLeft) + ")"
                          : bluetooth.deviceName !== "" ? "Connected: " + bluetooth.deviceName
                          : "No phone connected"
                }
            }

            Rectangle {
                visible: bluetooth.adapterPresent
                anchors { right: parent.right; rightMargin: 20; verticalCenter: parent.verticalCenter; verticalCenterOffset: 14 }
                width: pairText.width + 48
                height: 56
                radius: Theme.radius
                border.width: Theme.border
                border.color: bluetooth.pairing ? Theme.line : Theme.accent
                color: bluetooth.pairing ? (pairTap.pressed ? Theme.line : Theme.panelHi)
                                         : (pairTap.pressed ? Qt.darker(Theme.accent, 1.25) : Theme.accent)
                scale: pairTap.pressed ? 0.97 : 1
                Label {
                    id: pairText
                    anchors.centerIn: parent
                    text: bluetooth.pairing ? "Stop pairing" : "Pair phone"
                    color: bluetooth.pairing ? Theme.text : Theme.bg
                    font.pixelSize: Theme.fontBody - 2
                    font.weight: Font.DemiBold
                }
                TapHandler { id: pairTap; onTapped: bluetooth.setPairing(!bluetooth.pairing) }
            }
        }

        Card {
            Layout.fillWidth: true
            Layout.fillHeight: true
            heading: "About"

            Column {
                anchors { left: parent.left; top: parent.top; leftMargin: 20; topMargin: 52 }
                spacing: 8
                Label { text: "Baja OS"; color: Theme.text; font.pixelSize: Theme.fontTitle; font.weight: Font.DemiBold }
                Label { text: "2005 Subaru Baja Turbo carputer"; color: Theme.textDim; font.pixelSize: Theme.fontBody }
                Label {
                    text: demoMode ? "Running on simulated vehicle and media data" : "Live data"
                    color: Theme.textDim
                    font.pixelSize: Theme.fontBody
                }
                Label {
                    text: typeof spotify === "undefined" || !spotify.available ? "Spotify: not set up"
                          : !spotify.linked ? "Spotify: pick “" + (spotify.deviceName || "Baja") + "” in the Spotify app to link"
                          : "Spotify: linked as “" + spotify.deviceName + "”"
                    color: Theme.textDim
                    font.pixelSize: Theme.fontBody
                }
            }

            // Network: online state, Wi-Fi name and the address to SSH to.
            Column {
                anchors { left: parent.horizontalCenter; top: parent.top; topMargin: 52 }
                spacing: 8
                readonly property bool known: typeof network !== "undefined" && network.checked

                Row {
                    spacing: 12
                    Rectangle {
                        anchors.verticalCenter: parent.verticalCenter
                        width: 14; height: 14; radius: 7
                        color: !parent.parent.known ? Theme.textDim
                               : network.online ? Theme.ok : Theme.warn
                    }
                    Label {
                        text: !parent.parent.known ? "Checking network…"
                              : network.online ? "Online" : (network.ip ? "No internet" : "Offline")
                        font.pixelSize: Theme.fontTitle
                        font.weight: Font.DemiBold
                    }
                }
                Label {
                    visible: parent.known
                    text: network.ssid ? "Wi-Fi: " + network.ssid : "Wi-Fi: not connected"
                    color: Theme.textDim
                    font.pixelSize: Theme.fontBody
                }
                Label {
                    visible: parent.known
                    text: "IP: " + (network.ip || "none")
                    color: Theme.textDim
                    font.pixelSize: Theme.fontBody
                }
                Label {
                    visible: parent.known && network.ip !== ""
                    text: "ssh " + network.user + "@" + network.ip
                    color: Theme.textDim
                    font.pixelSize: Theme.fontSmall
                }
            }
        }
    }
}
