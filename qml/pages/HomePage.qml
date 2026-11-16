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

    // Coolant under 155 F with the engine known says "Warming up" (go easy on
    // the boost) until it reaches 160 F. The gap between the two lines holds
    // the last state, so the label can't flicker at the edge.
    readonly property real warmCoolantF: 160
    property bool warmingUp: false
    function updateWarmingUp() {
        if (!page.visible) return   // nobody sees the label; onVisibleChanged catches up
        if (!vehicle.engineKnown) warmingUp = false;
        else if (vehicle.coolant < warmCoolantF - 5) warmingUp = true;
        else if (vehicle.coolant >= warmCoolantF) warmingUp = false;
    }
    Component.onCompleted: updateWarmingUp()
    onVisibleChanged: if (visible) updateWarmingUp()
    Connections {
        target: vehicle
        function onChanged() { page.updateWarmingUp() }
    }

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
                HomeTurn { id: nextTurn; anchors { left: parent.left; right: parent.right; top: parent.top; margins: 12 } }
                // No fix, or the sky lost: say so, below the turn card while routing.
                HomeGpsStatus {
                    x: 12
                    y: 12 + (nextTurn.shown ? nextTurn.height + 12 : 0)
                }
                // Navigating: when you get there, how long and how far.
                HomeArrive { anchors { left: parent.left; bottom: parent.bottom; margins: 12 } }

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
            id: readoutCard
            objectName: "homeReadoutCard"
            Layout.fillWidth: true
            // Grows by a line while the engine note shows, so nothing overlaps.
            Layout.preferredHeight: engineNote.visible ? 184 : 152
            tappable: true
            onTapped: page.navigate(3)

            // Any engine warning (the MIL lamp included, which has no numeral to
            // turn Ember) gives the strip a steady Ember border, which stays
            // after the one-shot pulse ends. The change eases over 180 ms.
            // Set by a Binding at the bottom, like the readouts, so it reads
            // nothing while Home is hidden (vehicle.changed fires 5 times a second).
            property bool anyWarning: false
            border.color: anyWarning ? Theme.warn : Theme.line
            border.width: anyWarning ? Theme.border + 1 : Theme.border
            Behavior on border.color { ColorAnimation { duration: 180 } }

            ColumnLayout {
                anchors { fill: parent; margins: 20 }
                spacing: 6

                // With no adapter answering (and no demo) the engine readouts
                // are dashes; say why, and where the speed comes from.
                Label {
                    id: engineNote
                    objectName: "homeEngineNote"
                    Layout.fillWidth: true
                    visible: !vehicle.simulated && !vehicle.engineKnown
                    text: "Engine not connected" + (vehicle.speedKnown && !vehicle.live ? " · speed from GPS" : "")
                    color: Theme.textDim
                    font.pixelSize: Theme.fontSmall
                }

                RowLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Readout {
                        id: boostReadout
                        Layout.fillWidth: true
                        Layout.alignment: Qt.AlignBottom
                        Layout.preferredWidth: 1
                        label: "Boost"
                        widest: Units.metric ? "-0.00" : "-00.0"
                        unit: Units.boostUnit
                    }
                    Readout {
                        id: coolantReadout
                        Layout.fillWidth: true
                        Layout.alignment: Qt.AlignBottom
                        Layout.preferredWidth: 1
                        label: page.warmingUp ? "Warming up" : "Coolant"
                        widest: "000"
                        highlight: page.warmingUp
                        unit: Units.tempUnit
                    }
                    Readout {
                        id: batteryReadout
                        Layout.fillWidth: true
                        Layout.alignment: Qt.AlignBottom
                        Layout.preferredWidth: 1
                        label: "Battery"
                        widest: "00.0"
                        unit: "V"
                    }
                    Readout {
                        id: speedReadout
                        Layout.fillWidth: true
                        Layout.alignment: Qt.AlignBottom
                        Layout.preferredWidth: 1.5
                        // Speed is the figure a driver checks most, so it gets the big numeral.
                        numeralSize: 76
                        label: "Speed"
                        widest: "000"
                        unit: Units.speedUnit
                    }
                }
            }
        }
    }

    // The readouts follow the vehicle only while Home is on screen: changed
    // fires 5 times a second and nobody sees these on another page. A Binding
    // still evaluates its value while "when" is false, so each expression is
    // guarded by page.visible too and reads nothing while hidden. RestoreNone
    // keeps the last value when the binding pauses; they refresh on return. The
    // hidden branch is the target's own value, not undefined: Qt doesn't promise
    // "when" goes false before value is re-evaluated, and a stray undefined would
    // blank the readout and drop its warning flag.
    Binding { target: boostReadout; property: "value"; when: page.visible; restoreMode: Binding.RestoreNone
        value: page.visible ? (vehicle.engineKnown ? Units.boost(vehicle.boost).toFixed(Units.boostDecimals) : "—") : boostReadout.value }
    Binding { target: boostReadout; property: "warning"; when: page.visible; restoreMode: Binding.RestoreNone
        value: page.visible ? (vehicle.warnings.indexOf("boost") >= 0) : boostReadout.warning }
    Binding { target: coolantReadout; property: "value"; when: page.visible; restoreMode: Binding.RestoreNone
        value: page.visible ? (vehicle.engineKnown ? Math.round(Units.temp(vehicle.coolant)) : "—") : coolantReadout.value }
    Binding { target: coolantReadout; property: "warning"; when: page.visible; restoreMode: Binding.RestoreNone
        value: page.visible ? (vehicle.warnings.indexOf("coolant") >= 0) : coolantReadout.warning }
    Binding { target: batteryReadout; property: "value"; when: page.visible; restoreMode: Binding.RestoreNone
        value: page.visible ? (vehicle.voltageKnown ? vehicle.voltage.toFixed(1) : "—") : batteryReadout.value }
    Binding { target: batteryReadout; property: "warning"; when: page.visible; restoreMode: Binding.RestoreNone
        value: page.visible ? (vehicle.warnings.indexOf("voltage") >= 0) : batteryReadout.warning }
    Binding { target: speedReadout; property: "value"; when: page.visible; restoreMode: Binding.RestoreNone
        value: page.visible ? (vehicle.speedKnown ? Math.round(Units.speed(vehicle.speed)) : "—") : speedReadout.value }
    // Written as a length check so a vehicle without warnings is fine.
    Binding { target: readoutCard; property: "anyWarning"; when: page.visible; restoreMode: Binding.RestoreNone
        value: page.visible ? (typeof vehicle.warnings !== "undefined" && vehicle.warnings.length > 0) : readoutCard.anyWarning }
}
