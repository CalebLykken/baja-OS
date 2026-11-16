import QtQuick

// The time for the rail clock, `now`, updated once a minute, just after the
// minute changes. It used to wake every 5 seconds, so the minute on screen
// could be up to 5 seconds late, and the UI woke 12 times a minute for a
// value that changes once. Each tick works out the time to the next minute
// from the real clock, so it also lands right after the clock is set by GPS
// or NTP, and after the car has been asleep. It is a single-shot timer, so
// it is never left repeating.
Timer {
    id: tick
    property date now: new Date()
    running: true
    interval: tick.msToNextMinute(new Date())

    // Milliseconds from `d` to the next minute, plus a little so the tick
    // lands just after the minute changes and never a hair before it.
    function msToNextMinute(d) {
        return 60000 - (d.getSeconds() * 1000 + d.getMilliseconds()) + 20
    }

    onTriggered: {
        tick.now = new Date()
        interval = tick.msToNextMinute(tick.now)
        restart()
    }
}
