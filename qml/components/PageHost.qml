import QtQuick

// Holds one page and animates it in and out: a short crossfade with a
// slight slide toward the direction you navigated. The outgoing page leaves
// fast (160 ms) so two pages are drawn at once for less time; the incoming
// one fades in over 240 ms and slides 280 ms with a small OutBack overshoot
// so it settles into place. Both are the same one-shot animations as always,
// only their duration and easing are keyed on each Behavior's own targetValue
// (the value it is animating toward: 1 / 0 for opacity, 0 for x when coming
// in), not on the shown state. Hidden pages are made
// invisible once faded, so they cost nothing to draw (the 3D page included).
Item {
    id: host
    property int index
    property int current
    default property alias content: holder.data
    readonly property bool shown: current === index
    // A page given as `lazy` (instead of as a child) is built the first time it
    // is shown, or ahead of time once `preload` is set so the first
    // tap is still instant. Once built it is kept, so its scroll position and
    // open panels survive navigating away.
    property Component lazy: null
    property bool preload: false
    property bool everShown: shown
    // True once the page is there to use: always for a page given as a child,
    // and for a lazy one when its Loader has finished building it. Main.qml
    // chains the background preloads on this, one page after the previous.
    readonly property bool built: lazy === null || lazyLoader.status === Loader.Ready
    onShownChanged: if (shown) everShown = true

    opacity: shown ? 1 : 0
    visible: opacity > 0
    Behavior on opacity { id: fade; NumberAnimation { duration: fade.targetValue > 0 ? 240 : 160; easing.type: Easing.OutCubic } }

    Item {
        id: holder
        width: parent.width
        height: parent.height
        x: host.shown ? 0 : (host.index < host.current ? -40 : 40)
        Behavior on x {
            id: slide
            NumberAnimation {
                duration: slide.targetValue === 0 ? 280 : 160
                easing.type: slide.targetValue === 0 ? Easing.OutBack : Easing.OutCubic
                easing.overshoot: 1.0
            }
        }

        Loader {
            id: lazyLoader
            anchors.fill: parent
            sourceComponent: host.lazy
            active: host.lazy !== null && (host.everShown || host.preload)
            // Always synchronous: Rows, Repeaters and anchors in a page built by
            // an asynchronous Loader never laid out (every segmented control's
            // options piled up at x = 0, IconButtons lost their icons). The
            // preload timers still keep the build off the first frame.
        }
    }
}
