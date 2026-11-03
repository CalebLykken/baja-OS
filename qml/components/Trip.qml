import QtQuick

// This trip: from when the dashboard started (the truck was turned on)
// until now. Counted once a second from the speed the truck reports, so it
// runs whichever page is showing (Main.qml holds the one copy).
// The start time is worked back from the seconds counted here, not read
// once at boot: the Pi's clock at boot is the last shutdown time until
// chrony steps it, and a start stamped then would stay wrong all drive.
Item {
    id: trip
    property date started: new Date()
    property real runningSeconds: 0       // seconds this page has been counting
    property real metres: 0
    property real movingSeconds: 0        // time actually rolling, not stopped at lights
    property real peakBoost: Number.NEGATIVE_INFINITY   // psi, while the engine answers

    readonly property real averageMph: movingSeconds > 0 ? metres / movingSeconds / 0.44704 : 0
    readonly property bool boostKnown: isFinite(peakBoost)

    Timer {
        interval: 1000; running: true; repeat: true
        onTriggered: {
            trip.runningSeconds += 1
            trip.started = new Date(Date.now() - trip.runningSeconds * 1000)
            if (typeof vehicle === "undefined") return
            if (vehicle.speedKnown && vehicle.speed > 1) {
                trip.metres += vehicle.speed * 0.44704      // mph to metres in this second
                trip.movingSeconds += 1
            }
            if (vehicle.engineKnown && vehicle.boost > trip.peakBoost)
                trip.peakBoost = vehicle.boost
        }
    }
}
