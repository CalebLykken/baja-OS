import QtQuick

// This trip: from when the dashboard started (the truck was turned on)
// until now. Counted once a second from the speed the truck reports, so it
// runs whichever page is showing (Main.qml holds the one copy).
Item {
    id: trip
    readonly property date started: new Date()
    property real metres: 0
    property real movingSeconds: 0        // time actually rolling, not stopped at lights
    property real peakBoost: Number.NEGATIVE_INFINITY   // psi, while the engine answers

    readonly property real averageMph: movingSeconds > 0 ? metres / movingSeconds / 0.44704 : 0
    readonly property bool boostKnown: isFinite(peakBoost)

    Timer {
        interval: 1000; running: true; repeat: true
        onTriggered: {
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
