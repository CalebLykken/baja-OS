import QtQuick

// The next turn while a route is being driven, at the foot of the nav rail
// on the pages that don't show the map. Tap for Maps.
Rectangle {
    id: chip
    signal tapped()

    readonly property bool active: typeof routing !== "undefined" && routing.active
    property string icon: "straight"          // the turn shown; changes at the bottom of a swap
    property string seenIcon: ""              // the latest turn while routing, "" when not
    // A reroute keeps the route active, but the old turn no longer exists; show what
    // the Maps turn card shows until the new route lands.
    readonly property bool rerouting: active && routing.computing
    onReroutingChanged: if (!rerouting && active) turnSwap.restart()

    // A new route or turn is a moment, not a loop: one nudge when the chip appears.
    // A route that restarts mid-swap must not leave the icon half-faded or offset.
    onActiveChanged: {
        turnSwap.stop()
        turnIcon.opacity = 1
        shift.y = 0
        if (active) {
            seenIcon = routing.maneuverIcon || "straight"
            icon = seenIcon
        } else {
            seenIcon = ""
        }
    }

    // The nudge plays when the chip actually shows: on the first route, after a
    // warning clears, or after leaving Maps. visible follows opacity, so this fires
    // as the chip fades in and not while it is still hidden.
    onVisibleChanged: if (visible) pop.restart()

    // routing.maneuverIcon notifies with progressChanged (every GPS update), so only a
    // different turn name starts the swap.
    Connections {
        target: typeof routing !== "undefined" ? routing : null
        function onProgressChanged() {
            const next = chip.active ? routing.maneuverIcon || "straight" : ""
            if (next === "" || next === chip.seenIcon) return
            const first = chip.seenIcon === ""
            chip.seenIcon = next
            if (first || chip.rerouting) chip.icon = next   // behind the refresh icon, swap on its return
            else turnSwap.restart()
        }
    }

    width: 96
    height: column.implicitHeight + 16
    radius: Theme.radius
    color: tap.pressed ? Theme.panelHi : Theme.panel
    border.width: Theme.border
    border.color: Theme.accent
    opacity: active ? 1 : 0
    visible: opacity > 0
    Behavior on opacity { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }

    SequentialAnimation {
        id: pop
        NumberAnimation { target: chip; property: "scale"; from: 0.85; to: 1.08; duration: 160; easing.type: Easing.OutCubic }
        NumberAnimation { target: chip; property: "scale"; to: 1.0; duration: 140; easing.type: Easing.InOutQuad }
    }

    // The turn icon fades and rises out, swaps, then fades back in from below.
    SequentialAnimation {
        id: turnSwap
        ParallelAnimation {
            NumberAnimation { target: turnIcon; property: "opacity"; to: 0; duration: 100; easing.type: Easing.InQuad }
            NumberAnimation { target: shift; property: "y"; to: -6; duration: 100; easing.type: Easing.InQuad }
        }
        ScriptAction { script: { chip.icon = chip.seenIcon; shift.y = 6 } }
        ParallelAnimation {
            NumberAnimation { target: turnIcon; property: "opacity"; to: 1; duration: 150; easing.type: Easing.OutCubic }
            NumberAnimation { target: shift; property: "y"; to: 0; duration: 150; easing.type: Easing.OutCubic }
        }
    }

    Column {
        id: column
        anchors.centerIn: parent
        spacing: 2
        Icon {
            id: turnIcon
            objectName: "turnIcon"
            anchors.horizontalCenter: parent.horizontalCenter
            name: chip.rerouting ? "refresh" : chip.icon
            size: 36
            color: Theme.accent
            transform: Translate { id: shift; y: 0 }
        }
        Label {
            objectName: "turnLabel"
            anchors.horizontalCenter: parent.horizontalCenter
            elide: Text.ElideRight
            width: Math.min(implicitWidth, chip.width - 12)
            numeric: true
            font.pixelSize: Theme.fontSmall
            font.weight: Font.DemiBold
            text: !chip.active ? "" : chip.rerouting ? "Rerouting" : routing.arrived ? "Arrived" : Units.distanceText(routing.distanceToTurn)
        }
    }

    TapHandler { id: tap; onTapped: chip.tapped() }
}
