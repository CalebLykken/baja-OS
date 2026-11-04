import QtQuick

// Holds one page and animates it in and out: a short crossfade with a
// slight slide toward the direction you navigated. The outgoing page leaves
// fast (160 ms) so two pages are drawn at once for less time; the incoming
// one fades in over 240 ms and slides 280 ms with a small OutBack overshoot
// so it settles into place. Both are the same one-shot animations as always,
// only their duration and easing depend on `shown` (a Behavior runs after the
// property changed, so it reads the new state). Hidden pages are made
// invisible once faded, so they cost nothing to draw (the 3D page included).
Item {
    id: host
    property int index
    property int current
    default property alias content: holder.data
    readonly property bool shown: current === index
    // A page given as `lazy` (instead of as a child) is built the first time it
    // is shown, or quietly in the background once `preload` is set so the first
    // tap is still instant. Once built it is kept, so its scroll position and
    // open panels survive navigating away.
    property Component lazy: null
    property bool preload: false
    property bool everShown: shown
    onShownChanged: if (shown) everShown = true

    opacity: shown ? 1 : 0
    visible: opacity > 0
    Behavior on opacity { NumberAnimation { duration: host.shown ? 240 : 160; easing.type: Easing.OutCubic } }

    Item {
        id: holder
        width: parent.width
        height: parent.height
        x: host.shown ? 0 : (host.index < host.current ? -40 : 40)
        Behavior on x {
            NumberAnimation {
                duration: host.shown ? 280 : 160
                easing.type: host.shown ? Easing.OutBack : Easing.OutCubic
                easing.overshoot: 1.0
            }
        }

        Loader {
            id: lazyLoader
            anchors.fill: parent
            sourceComponent: host.lazy
            active: host.lazy !== null && (host.everShown || host.preload)
            // Background loads are incremental; a page you are waiting for is not.
            asynchronous: !host.shown
            // Shown while a background load is still going: restart it
            // synchronously so the page is there at once.
            Connections {
                target: host
                function onShownChanged() {
                    if (host.shown && lazyLoader.status === Loader.Loading) {
                        lazyLoader.asynchronous = false
                        lazyLoader.active = false
                        lazyLoader.active = true
                        lazyLoader.active = Qt.binding(() => host.lazy !== null && (host.everShown || host.preload))
                        lazyLoader.asynchronous = Qt.binding(() => !host.shown)
                    }
                }
            }
        }
    }
}
