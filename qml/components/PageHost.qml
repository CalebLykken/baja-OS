import QtQuick

// Holds one page and animates it in and out: a short crossfade with a
// slight slide toward the direction you navigated. Hidden pages are made
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
    Behavior on opacity { NumberAnimation { duration: 240; easing.type: Easing.OutCubic } }

    Item {
        id: holder
        width: parent.width
        height: parent.height
        x: host.shown ? 0 : (host.index < host.current ? -40 : 40)
        Behavior on x { NumberAnimation { duration: 240; easing.type: Easing.OutCubic } }

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
