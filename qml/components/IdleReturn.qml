import QtQuick

// Fires idle() once after `timeout` ms with no touch, but only while `active`.
// Used to bring the dashboard back to Home when Settings or the Truck page is
// left open. The timer only exists to run while active, so on every other
// page nothing runs. The PointHandler is passive: it sees every touch without
// grabbing it, so the page underneath still gets all of them.
Item {
    id: root
    anchors.fill: parent

    property bool active: false
    property int timeout: 90000
    signal idle()

    // Any touch (or the owner, when it decides to wait another round) starts
    // the wait again.
    function poke() {
        if (root.active) timer.restart()
    }

    Timer {
        id: timer
        interval: root.timeout
        running: root.active
        onTriggered: root.idle()
    }

    PointHandler { onPointChanged: root.poke() }
}
