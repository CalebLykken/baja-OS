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

                // Tap or drag anywhere along the bar; the tall hit area is
                // easier to land on in a moving car than the 10 px bar.
                Item {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    ProgressBar {
                        anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter }
                        height: 10
                        radius: 5
                        value: display.brightness / 100
                    }
                    MouseArea {
                        anchors.fill: parent
                        function apply(x) { display.setBrightness(Math.round(100 * x / width)) }
                        onPressed: (mouse) => apply(mouse.x)
                        onPositionChanged: (mouse) => apply(mouse.x)
                    }
                }

                Label {
                    Layout.preferredWidth: 64
                    horizontalAlignment: Text.AlignRight
                    text: display.brightness + "%"
                    color: Theme.text
                    font.pixelSize: Theme.fontBody
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

                Row {
                    anchors { left: parent.left; leftMargin: 20; verticalCenter: parent.verticalCenter; verticalCenterOffset: 14 }
                    spacing: 12
                    Repeater {
                        model: Theme.styleNames
                        Rectangle {
                            readonly property bool selected: Theme.style === modelData
                            width: styleText.width + 48
                            height: 56
                            radius: 28
                            color: selected ? Theme.accent : Theme.panelHi
                            Label {
                                id: styleText
                                anchors.centerIn: parent
                                text: modelData.charAt(0).toUpperCase() + modelData.slice(1)
                                color: parent.selected ? Theme.bg : Theme.text
                                font.pixelSize: Theme.fontBody - 2
                            }
                            TapHandler { onTapped: Theme.style = modelData }
                        }
                    }
                }
            }

            Card {
                Layout.fillWidth: true
                Layout.fillHeight: true
                heading: "Units"

                Row {
                    anchors { left: parent.left; leftMargin: 20; verticalCenter: parent.verticalCenter; verticalCenterOffset: 14 }
                    spacing: 12
                    Repeater {
                        model: [{ label: "Imperial (mph, °F)", metric: false }, { label: "Metric (km/h, °C)", metric: true }]
                        Rectangle {
                            readonly property bool selected: page.metric === modelData.metric
                            width: unitText.width + 48
                            height: 56
                            radius: 28
                            color: selected ? Theme.accent : Theme.panelHi
                            Label {
                                id: unitText
                                anchors.centerIn: parent
                                text: modelData.label
                                color: parent.selected ? Theme.bg : Theme.text
                                font.pixelSize: Theme.fontBody - 2
                            }
                            TapHandler { onTapped: page.metric = modelData.metric }
                        }
                    }
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
                radius: 28
                color: bluetooth.pairing ? Theme.panelHi : Theme.accent
                Label {
                    id: pairText
                    anchors.centerIn: parent
                    text: bluetooth.pairing ? "Stop" : "Pair phone"
                    color: bluetooth.pairing ? Theme.text : Theme.bg
                    font.pixelSize: Theme.fontBody - 2
                }
                TapHandler { onTapped: bluetooth.setPairing(!bluetooth.pairing) }
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
