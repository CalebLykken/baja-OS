import QtQuick

// This trip: from when the dashboard started (the truck was turned on)
// until now. Counted once a second from the speed the truck reports, so it
// runs whichever page is showing (Main.qml holds the one copy).
// The start time is worked back from the seconds counted here, not read
// once at boot: the Pi's clock at boot is the last shutdown time until
// chrony steps it, and a start stamped then would stay wrong all drive.
// A restart of the dashboard mid-drive (the watchdog, the updater at a stop)
// carries the trip on: it is saved every 30 s of rolling, at a milestone, when
// the truck stops and when the dashboard quits, and read back at start-up when it is the same boot (backend/trip.py). What
// is read back is what the milestones compare against, so none fires twice.
Item {
    id: trip
    property date started: new Date()
    property real runningSeconds: 0       // seconds this page has been counting
    property real metres: 0
    property real movingSeconds: 0        // time actually rolling, not stopped at lights
    property real peakBoost: Number.NEGATIVE_INFINITY   // psi, while the engine answers
    property bool wasMoving: false        // rolling at the last tick, to catch the stop

    readonly property real averageMph: movingSeconds > 0 ? metres / movingSeconds / 0.44704 : 0
    readonly property bool boostKnown: isFinite(peakBoost)

    // Fired once when this trip crosses a round distance or an hour of driving.
    signal milestone(string text)

    function save() {
        if (typeof tripStore !== "undefined")
            tripStore.save(trip.metres, trip.movingSeconds, trip.runningSeconds, trip.peakBoost)
    }

    // The dashboard is quitting (main.py asks before settings are flushed).
    Connections {
        target: typeof tripStore !== "undefined" ? tripStore : null
        function onSaveRequested() { trip.save() }
    }

    Component.onCompleted: {
        if (typeof tripStore === "undefined") return
        var r = tripStore.restore()
        if (r.metres === undefined) return
        trip.metres = r.metres
        trip.movingSeconds = r.movingSeconds
        trip.runningSeconds = r.runningSeconds
        if (r.peakBoost != null) trip.peakBoost = r.peakBoost
        trip.started = new Date(Date.now() - trip.runningSeconds * 1000)
    }

    // The message for a threshold crossed between the previous and current
    // values, or "". Only a crossing counts, so changing units mid-trip
    // (same metres, different display unit) says nothing. Distance wins
    // over time when both land in the same second.
    function milestoneText(prevMetres, metres, prevSeconds, seconds, metric) {
        var unit = metric ? 1000 : 1609.344
        var before = prevMetres / unit, now = metres / unit
        var marks = [10, 25, 50]
        for (var i = 0; i < marks.length; i++)
            if (before < marks[i] && now >= marks[i])
                return marks[i] + (metric ? " km" : " miles") + " this trip"
        if (now >= 100 && Math.floor(now / 100) > Math.floor(before / 100))
            return Math.floor(now / 100) * 100 + (metric ? " km" : " miles") + " this trip"
        var hours = Math.floor(seconds / 3600)
        if (hours > 0 && hours > Math.floor(prevSeconds / 3600)) {
            if (hours === 1) return "An hour of driving"
            if (hours === 2) return "Two hours of driving"
            return hours + " hours of driving"
        }
        return ""
    }

    Timer {
        interval: 1000; running: true; repeat: true
        onTriggered: {
            trip.runningSeconds += 1
            trip.started = new Date(Date.now() - trip.runningSeconds * 1000)
            if (typeof vehicle === "undefined") return
            var moving = vehicle.speedKnown && vehicle.speed > 1
            if (moving) {
                var prevMetres = trip.metres, prevSeconds = trip.movingSeconds
                trip.metres += vehicle.speed * 0.44704      // mph to metres in this second
                trip.movingSeconds += 1
                var text = trip.milestoneText(prevMetres, trip.metres, prevSeconds,
                                              trip.movingSeconds, Units.metric)
                if (text !== "") trip.milestone(text)
                if (text !== "" || trip.movingSeconds % 30 === 0) trip.save()
            }
            if (vehicle.engineKnown && vehicle.boost > trip.peakBoost)
                trip.peakBoost = vehicle.boost
            // One save per stop; nothing while parked.
            if (trip.wasMoving && !moving) trip.save()
            trip.wasMoving = moving
        }
    }
}
