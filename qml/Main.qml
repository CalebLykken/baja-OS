import QtQuick
import QtQuick.Layouts
import QtQuick.Window
import "components"
import "pages"

// Root window: nav rail on the left, status bar + pages on the right.
// Sized for the 8" 1280x800 panel; main.py goes full screen on the Pi.
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
        { icon: "settings", label: "Settings" }
    ]

    // Lets screenshot tooling (and later a hardware button) switch pages.
    function showPage(i) { page = i }
    function setStyle(name) { Theme.style = name }

    // Style: --style for this run if given, else the one saved last time.
    // Any change (e.g. from Settings) is saved for the next start.
    Component.onCompleted: {
        if (typeof startStyle !== "undefined" && startStyle)
            Theme.style = startStyle
        else if (typeof settings !== "undefined")
            Theme.style = settings.get("style", "amber")
    }
    Connections {
        target: Theme
        function onStyleChanged() {
            if (typeof settings !== "undefined") settings.set("style", Theme.style)
        }
    }

    Backdrop { anchors.fill: parent }

    Rectangle {
        id: rail
        width: 112
        anchors { left: parent.left; top: parent.top; bottom: parent.bottom }
        color: Theme.backdrop === "none" ? Theme.bg : "transparent"

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

        StatusBar {
            Layout.fillWidth: true
            title: root.pages[root.page].label
        }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: root.page

            HomePage { onNavigate: (i) => root.page = i }
            MusicPage { onNavigate: (i) => root.page = i }
            MapsPage { onNavigate: (i) => root.page = i }
            GaugesPage { onNavigate: (i) => root.page = i }
            SettingsPage { onNavigate: (i) => root.page = i }
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

    // Startup animation, on top of everything until it fades out.
    Splash {
        anchors.fill: parent
        visible: typeof showSplash === "undefined" || showSplash
    }
}
