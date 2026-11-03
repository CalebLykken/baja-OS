import QtQuick
import QtQuick.Layouts
import "../components"

// At-a-glance screen: the music card, a small live map, and the key
// readouts, like CarPlay's split screen.
Item {
    id: page
    signal navigate(int index)

    property bool mapReady: false
    readonly property alias mapSlot: slot   // where Main.qml puts the map while Home shows

    ColumnLayout {
        anchors.fill: parent
        spacing: Theme.gap

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: Theme.gap

            NowPlaying {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.preferredWidth: 3
                onOpenMusic: page.navigate(1)
            }

            // The map, small: the same map as the Maps page (Main.qml moves
            // it here), following the truck. Tap it for the full map.
            Rectangle {
                id: mapTile
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.preferredWidth: 2
                radius: Theme.radius
                color: Theme.panel

                Item { id: slot; anchors { fill: parent; margins: Theme.border } }

                // Until the map is drawn (or without one): what it is.
                Column {
                    visible: !page.mapReady
                    anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: 20 }
                    spacing: 10
                    Icon {
                        anchors.horizontalCenter: parent.horizontalCenter
                        name: "map"
                        color: Theme.textDim
                        size: 72
                    }
                    Label {
                        width: parent.width
                        horizontalAlignment: Text.AlignHCenter
                        text: "Maps"
                        font.pixelSize: Theme.fontTitle
                        font.weight: Font.DemiBold
                    }
                    Label {
                        width: parent.width
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.WordWrap
                        text: typeof maps === "undefined" || !maps.ready ? "No map installed yet"
                              : maps.region + "\nworks with no signal"
                        color: Theme.textDim
                        font.pixelSize: Theme.fontBody
                    }
                }

                // Navigating: the next turn over the top of the map, on the
                // same dark card as the Maps page.
                Rectangle {
                    visible: typeof routing !== "undefined" && routing.active
                    anchors { left: parent.left; right: parent.right; top: parent.top; margins: 12 }
                    height: miniTurn.implicitHeight + 28
                    radius: Theme.radius
                    color: Theme.base.panel
                    RowLayout {
                        id: miniTurn
                        anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: 14 }
                        spacing: 12
                        Icon {
                            Layout.alignment: Qt.AlignTop
                            name: typeof routing !== "undefined" ? routing.maneuverIcon || "straight" : "straight"
                            size: 64
                            color: Theme.base.text
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 0
                            Label {
                                visible: typeof routing !== "undefined" && !routing.arrived
                                numeric: true
                                text: typeof routing !== "undefined" ? Units.distanceText(routing.distanceToTurn) : ""
                                color: Theme.base.text
                                font.pixelSize: Theme.fontReadout
                            }
                            Label {
                                Layout.fillWidth: true
                                wrapMode: Text.WordWrap
                                maximumLineCount: 2
                                elide: Text.ElideRight
                                text: typeof routing !== "undefined" ? routing.instruction : ""
                                color: Theme.base.text
                                font.pixelSize: Theme.fontSmall
                                font.weight: Font.DemiBold
                            }
                        }
                    }
                }
                Rectangle {
                    visible: typeof routing !== "undefined" && routing.active
                    anchors { left: parent.left; bottom: parent.bottom; margins: 12 }
                    width: arriveText.implicitWidth + 32
                    height: 64
                    radius: Theme.radius
                    color: Theme.panel
                    border.width: Theme.border
                    border.color: Theme.line
                    Label {
                        id: arriveText
                        anchors.centerIn: parent
                        text: typeof routing !== "undefined"
                              ? "Arrive " + Units.arrivalText(routing.remainingTime) + ", " + Units.distanceText(routing.remainingDistance) : ""
                        font.pixelSize: Theme.fontSmall
                        font.weight: Font.DemiBold
                    }
                }

                // Round off the map's square corners, then the frame.
                Repeater {
                    model: 4
                    Canvas {
                        readonly property bool atRight: index === 1 || index === 2
                        readonly property bool atBottom: index >= 2
                        width: Theme.radius; height: Theme.radius
                        x: atRight ? mapTile.width - width : 0
                        y: atBottom ? mapTile.height - height : 0
                        rotation: [0, 90, 180, 270][index]
                        onPaint: {
                            var ctx = getContext("2d"), r = width
                            ctx.reset()
                            ctx.fillStyle = Theme.bg
                            ctx.beginPath()
                            ctx.moveTo(0, 0); ctx.lineTo(r, 0)
                            ctx.arc(r, r, r, -Math.PI / 2, Math.PI, true)
                            ctx.closePath()
                            ctx.fill()
                        }
                        Connections {
                            target: Theme
                            function onStyleChanged() { requestPaint() }
                            function onDarkChanged() { requestPaint() }
                        }
                    }
                }
                Rectangle {
                    anchors.fill: parent
                    radius: Theme.radius
                    color: "transparent"
                    border.width: Theme.border
                    border.color: Theme.line
                }
                // The small map isn't for dragging: any tap opens Maps.
                MouseArea { anchors.fill: parent; onClicked: page.navigate(2) }
            }
        }

        Card {
            Layout.fillWidth: true
            Layout.preferredHeight: 128
            tappable: true
            onTapped: page.navigate(3)

            RowLayout {
                anchors { fill: parent; margins: 20 }
                Readout {
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    label: "Boost"
                    value: vehicle.engineKnown ? Units.boost(vehicle.boost).toFixed(Units.boostDecimals) : "—"
                    unit: Units.boostUnit
                    warning: vehicle.warnings.indexOf("boost") >= 0
                }
                Readout {
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    label: "Coolant"
                    value: vehicle.engineKnown ? Math.round(Units.temp(vehicle.coolant)) : "—"
                    unit: Units.tempUnit
                    warning: vehicle.warnings.indexOf("coolant") >= 0
                }
                Readout {
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    label: "Battery"
                    value: vehicle.voltageKnown ? vehicle.voltage.toFixed(1) : "—"
                    unit: "V"
                    warning: vehicle.warnings.indexOf("voltage") >= 0
                }
                Readout {
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    label: "Speed"
                    value: vehicle.speedKnown ? Math.round(Units.speed(vehicle.speed)) : "—"
                    unit: Units.speedUnit
                }
            }
        }
    }
}
