import QtQuick
import QtQuick.Layouts
import QtQuick.Window
import "components"
import "pages"

// Root window: nav rail on the left, status bar + pages on the right.
// Sized for the 8" 1280x800 panel; main.py goes full screen on the Pi.
//
// Maps and Music are the exceptions: they fill everything right of the
// rail (no status bar; the clock moves into the rail), like CarPlay. There
// is one map engine for the whole dashboard: it sits full size on Maps and
// small in the Home page's map tile, moved to whichever is showing.
Window {
    id: root
    width: 1280
    height: 800
    visible: true
    color: Theme.bg
    title: "Baja Carputer"

    property int page: 0
    readonly property var pages: [
        { icon: "home", label: "Home" },
        { icon: "music", label: "Music" },
        { icon: "map", label: "Maps" },
        { icon: "speed", label: "Gauges" },
        { icon: "car", label: "Truck" },
        { icon: "settings", label: "Settings" }
    ]
    readonly property bool onMaps: page === 2
    readonly property bool fullPage: page === 1 || page === 2     // Music and Maps

    // Overpass (after US highway-sign lettering) for the map and its
    // controls; bundled, so nothing needs installing on the Pi.
    FontLoader { source: "assets/fonts/Overpass-Regular.ttf" }
    FontLoader { source: "assets/fonts/Overpass-SemiBold.ttf" }
    FontLoader { source: "assets/fonts/Overpass-Bold.ttf" }

    // Lets screenshot tooling (and later a hardware button) switch pages.
    function showPage(i) { page = i }
    function setStyle(name) { Theme.style = name }

    // Style: --style for this run if given, else the one saved last time.
    // Any change (e.g. from Settings) is saved for the next start.
    Component.onCompleted: {
        if (typeof startStyle !== "undefined" && startStyle)
            Theme.style = startStyle
        else if (typeof settings !== "undefined")
            Theme.style = settings.get("style", "trail")
        // QSettings hands booleans back as strings.
        if (typeof settings !== "undefined") {
            Units.metric = String(settings.get("metric", "false")) === "true"
            Units.clock24 = String(settings.get("clock24", "false")) === "true"
            Units.appearance = String(settings.get("appearance", "auto"))
        }
    }
    Connections {
        target: Theme
        function onStyleChanged() {
            if (typeof settings !== "undefined") settings.set("style", Theme.style)
        }
    }
    Connections {
        target: Units
        function onMetricChanged() { settings.set("metric", Units.metric ? "true" : "false") }
        function onClock24Changed() { settings.set("clock24", Units.clock24 ? "true" : "false") }
        function onAppearanceChanged() { settings.set("appearance", Units.appearance) }
    }

    // Light by day, dark at night (by the sun where the truck is), unless
    // Settings picks one: the whole dashboard and the map together.
    Binding {
        target: Theme
        property: "dark"
        value: Units.appearance === "dark"
               || (Units.appearance !== "light" && typeof display !== "undefined" && display.sunDown)
    }

    // A destination sent from the phone: open the map with it, ready for Go.
    Connections {
        target: typeof phone !== "undefined" ? phone : null
        function onReceived(place) {
            if (typeof display !== "undefined") display.wake()
            root.page = 2
            mapsPage.receive(place)
        }
    }

    // ---- the one map engine ------------------------------------------------------
    property bool mapWanted: false
    property bool mapReady: false
    property string mapProblem: ""
    readonly property var mapView: mapLoader.item
    // Start it once the start-up screen is done (it's on Home too).
    Timer { interval: 3000; running: true; onTriggered: root.mapWanted = true }
    onPageChanged: if (page === 0 || page === 2) mapWanted = true

    Loader {
        id: mapLoader
        active: root.mapWanted && typeof maps !== "undefined" && maps.webEngine && maps.ready
        source: "pages/MapView.qml"
        onStatusChanged: if (status === Loader.Error) root.mapProblem = "The map engine didn't start"
        onLoaded: {
            item.parent = Qt.binding(() => root.onMaps ? mapsPage.mapSlot : homePage.mapSlot)
            item.mode = Qt.binding(() => Theme.dark ? "night" : "day")
            item.insetLeft = Qt.binding(() => root.onMaps ? mapsPage.mapInsetLeft : 0)
        }
    }
    Connections {
        target: root.mapView
        ignoreUnknownSignals: true
        function onReady(ms) { root.mapReady = true; root.mapProblem = ""; console.log("Map: drawn in " + ms + " ms") }
        function onFailed(message) { root.mapProblem = message }
        function onCrashed() { root.mapReady = false }      // until it draws again
        function onBenchDone(result) { console.log("Map bench: " + JSON.stringify(result)) }
    }

    Backdrop { anchors.fill: parent }

    Rectangle {
        id: rail
        width: 112
        anchors { left: parent.left; top: parent.top; bottom: parent.bottom }
        color: Theme.backdrop === "none" || root.onMaps ? Theme.bg : "transparent"

        // On Maps and Music the status bar gives way; the time sits here.
        Label {
            visible: root.fullPage
            anchors { horizontalCenter: parent.horizontalCenter; top: parent.top; topMargin: 22 }
            property date now: new Date()
            text: Units.timeText(now)
            numeric: true
            font.pixelSize: Theme.fontBody
            font.weight: Font.DemiBold
            Timer { interval: 5000; running: true; repeat: true; onTriggered: parent.now = new Date() }
        }

        // An engine reading from the car out of range: here, so it shows
        // on every page, Maps and Music included. Tap for the gauges.
        EngineWarning {
            anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 8 }
            onTapped: root.page = 3
        }

        Column {
            anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter }
            Repeater {
                model: root.pages
                NavButton {
                    icon: modelData.icon
                    label: modelData.label
                    active: root.page === index
                    onClicked: root.page = index
                }
            }
        }

        Rectangle {
            width: 1
            color: Theme.line
            anchors { right: parent.right; top: parent.top; bottom: parent.bottom }
        }
    }

    ColumnLayout {
        anchors {
            left: rail.right; right: parent.right; top: parent.top; bottom: parent.bottom
            leftMargin: 24; rightMargin: 24; bottomMargin: 20
        }
        spacing: 8
        opacity: root.fullPage ? 0 : 1
        visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: 200 } }

        StatusBar {
            Layout.fillWidth: true
            title: root.pages[root.page].label
            showTurn: !root.fullPage && root.page !== 0    // Home's map tile shows it
            onTurnTapped: root.page = 2
        }

        // Pages crossfade and slide as you move between them (PageHost).
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            PageHost { anchors.fill: parent; index: 0; current: root.page
                HomePage {
                    id: homePage
                    anchors.fill: parent
                    mapReady: root.mapReady
                    onNavigate: (i) => root.page = i
                }
            }
            PageHost { anchors.fill: parent; index: 3; current: root.page
                GaugesPage { anchors.fill: parent; onNavigate: (i) => root.page = i } }
            PageHost { anchors.fill: parent; index: 4; current: root.page
                TruckPage { anchors.fill: parent; onNavigate: (i) => root.page = i } }
            PageHost { anchors.fill: parent; index: 5; current: root.page
                SettingsPage { anchors.fill: parent; onNavigate: (i) => root.page = i } }
        }
    }

    // Music: everything right of the rail.
    PageHost {
        anchors { left: rail.right; right: parent.right; top: parent.top; bottom: parent.bottom }
        index: 1
        current: root.page
        MusicPage { anchors.fill: parent; onNavigate: (i) => root.page = i }
    }

    // Maps: everything right of the rail.
    PageHost {
        anchors { left: rail.right; right: parent.right; top: parent.top; bottom: parent.bottom }
        index: 2
        current: root.page
        MapsPage {
            id: mapsPage
            anchors.fill: parent
            map: root.mapView
            mapReady: root.mapReady
            problem: root.mapProblem
            onNavigate: (i) => root.page = i
        }
    }

    // Software dimming for screens without DDC/CI brightness (e.g. a Mac).
    // Never fully black, and it lets touches through to the UI below.
    Rectangle {
        anchors.fill: parent
        visible: !display.hardware
        color: "black"
        opacity: (1 - display.brightness / 100) * 0.85
    }

    // "Screen off": a black layer over the pages and the dim overlay (the
    // backlight itself is not driven yet, see Display._drive_panel). The tap
    // that wakes it is swallowed so it doesn't press anything underneath.
    // The shutdown prompt below stays above it.
    Rectangle {
        anchors.fill: parent
        color: "black"
        visible: typeof display !== "undefined" && display.screenOff
        MouseArea {
            anchors.fill: parent
            onPressed: (mouse) => { mouse.accepted = true; display.wake() }
        }
    }
    Connections {
        target: typeof keyOff !== "undefined" ? keyOff : null
        function onChanged() {
            if (typeof display !== "undefined" && (keyOff.countdown >= 0 || keyOff.error !== ""))
                display.wake()
        }
    }

    // An overheating or charging warning brings the screen back (once per
    // warning, so it can be blanked again while the warning holds).
    readonly property bool urgentWarning: typeof vehicle !== "undefined"
        && (vehicle.warnings.indexOf("coolant") >= 0 || vehicle.warnings.indexOf("voltage") >= 0)
    onUrgentWarningChanged: if (urgentWarning && typeof display !== "undefined") display.wake()

    // A phone wants to pair (backend/btagent.py): nothing pairs without a
    // tap here. Phones with no screen have no code to compare.
    Rectangle {
        id: pairPrompt
        readonly property bool asking: typeof bluetooth !== "undefined" && bluetooth.pairPending
        readonly property string name: asking ? bluetooth.pairName : ""
        readonly property string address: asking ? bluetooth.pairAddress : ""
        readonly property string code: asking ? bluetooth.pairCode : ""
        anchors.fill: parent
        color: Qt.rgba(0, 0, 0, 0.6)
        opacity: asking ? 1 : 0
        visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: 200 } }
        MouseArea { anchors.fill: parent }        // nothing underneath while it's up

        Card {
            anchors.centerIn: parent
            width: 720
            height: pairColumn.implicitHeight + 64
            ColumnLayout {
                id: pairColumn
                anchors { left: parent.left; right: parent.right; top: parent.top; margins: 32 }
                spacing: 12
                Label {
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                    textFormat: Text.PlainText      // the name comes from the other device
                    text: "Pair with " + pairPrompt.name + "?"
                    font.pixelSize: Theme.fontTitle
                    font.weight: Font.DemiBold
                }
                Label {
                    visible: pairPrompt.address !== "" && pairPrompt.address !== pairPrompt.name
                    color: Theme.textDim
                    font.pixelSize: Theme.fontSmall
                    text: pairPrompt.address
                }
                Label {
                    visible: pairPrompt.code !== ""
                    Layout.topMargin: 8
                    numeric: true
                    text: pairPrompt.code
                    font.pixelSize: Theme.fontHuge
                    font.weight: Theme.numWeight
                    font.letterSpacing: 6
                }
                Label {
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    color: Theme.textDim
                    font.pixelSize: Theme.fontBody
                    text: pairPrompt.code !== "" ? "Check it matches the code on the phone"
                                                 : "This phone shows no code, so there's no code to compare. Pair only if it's yours."
                }
                RowLayout {
                    Layout.topMargin: 12
                    spacing: 14
                    TextButton {
                        Layout.preferredWidth: 300; Layout.preferredHeight: Theme.touch
                        text: "Pair"; primary: true
                        onClicked: bluetooth.acceptPairing()
                    }
                    TextButton {
                        Layout.preferredWidth: 300; Layout.preferredHeight: Theme.touch
                        text: "Cancel"
                        onClicked: bluetooth.cancelPairing()
                    }
                }
            }
        }
    }

    // The truck was turned off: the Pi shuts down at the end of the
    // countdown (backend/ignition.py) unless "Keep on" is tapped. If the
    // shutdown fails, it says so instead, until OK.
    Rectangle {
        id: keyOffPrompt
        readonly property int secondsLeft: typeof keyOff === "undefined" ? -1 : keyOff.countdown
        readonly property bool failed: typeof keyOff !== "undefined" && keyOff.error !== ""
        property bool showError: false            // kept while it fades out
        onFailedChanged: if (failed) showError = true
        onSecondsLeftChanged: if (secondsLeft >= 0) showError = false
        anchors.fill: parent
        color: Qt.rgba(0, 0, 0, 0.6)
        opacity: secondsLeft >= 0 || failed ? 1 : 0
        visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: 200 } }
        MouseArea { anchors.fill: parent }        // nothing underneath while it's up

        Card {
            anchors.centerIn: parent
            width: 720
            height: promptColumn.implicitHeight + 64
            ColumnLayout {
                id: promptColumn
                anchors { left: parent.left; right: parent.right; top: parent.top; margins: 32 }
                spacing: 12
                Label {
                    text: keyOffPrompt.showError ? "Couldn't shut down" : "The truck is off"
                    font.pixelSize: Theme.fontTitle
                    font.weight: Font.DemiBold
                }
                Label {
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    color: Theme.textDim
                    font.pixelSize: Theme.fontBody
                    text: keyOffPrompt.showError
                          ? "Run deploy/setup-pi.sh once on the Pi so the dashboard can shut it down. Until then the power relay cuts the power without a clean shutdown."
                          : "Shutting down in " + Math.max(0, keyOffPrompt.secondsLeft) + " s"
                }
                Label {
                    visible: keyOffPrompt.showError
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    color: Theme.textDim
                    font.pixelSize: Theme.fontSmall
                    text: typeof keyOff !== "undefined" ? keyOff.error : ""
                }
                RowLayout {
                    visible: keyOffPrompt.showError
                    Layout.topMargin: 12
                    TextButton {
                        Layout.preferredWidth: 300; Layout.preferredHeight: Theme.touch
                        text: "OK"; primary: true
                        onClicked: keyOff.dismiss()
                    }
                }
                RowLayout {
                    visible: !keyOffPrompt.showError
                    Layout.topMargin: 12
                    spacing: 14
                    TextButton {
                        Layout.preferredWidth: 300; Layout.preferredHeight: Theme.touch
                        text: "Keep on"; primary: true
                        onClicked: keyOff.keepOn()
                    }
                    TextButton {
                        Layout.preferredHeight: Theme.touch
                        icon: "power"; text: "Shut down now"; danger: true
                        onClicked: system.powerOff()
                    }
                }
            }
        }
    }

    // The last start had to take an update back (backend/updater.py): say
    // so, once, until OK.
    Rectangle {
        id: updateNotice
        readonly property string text: typeof updater === "undefined" ? "" : updater.notice
        anchors.fill: parent
        color: Qt.rgba(0, 0, 0, 0.6)
        visible: text !== ""
        MouseArea { anchors.fill: parent }        // nothing underneath while it's up

        Card {
            anchors.centerIn: parent
            width: 720
            height: noticeColumn.implicitHeight + 64
            ColumnLayout {
                id: noticeColumn
                anchors { left: parent.left; right: parent.right; top: parent.top; margins: 32 }
                spacing: 12
                Label {
                    text: "Software update"
                    font.pixelSize: Theme.fontTitle
                    font.weight: Font.DemiBold
                }
                Label {
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    color: Theme.textDim
                    font.pixelSize: Theme.fontBody
                    text: updateNotice.text
                }
                TextButton {
                    Layout.topMargin: 12
                    Layout.preferredWidth: 300; Layout.preferredHeight: Theme.touch
                    text: "OK"; primary: true
                    onClicked: updater.dismissNotice()
                }
            }
        }
    }

    // Startup animation, on top of everything until it fades out.
    Splash {
        anchors.fill: parent
        visible: typeof showSplash === "undefined" || showSplash
    }
}
