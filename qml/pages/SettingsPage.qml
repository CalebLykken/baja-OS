import QtQuick
import QtQuick.Layouts
import "../components"

// Settings in sections down the left (Display, Sound, Wi-Fi, Bluetooth, Map,
// System, About), with the chosen section's cards on the right; long ones
// scroll. Joining a Wi-Fi network opens a password sheet with the on-screen
// keyboard.
Item {
    id: page
    objectName: "settingsPage"
    signal navigate(int index)

    property int section: 0
    readonly property var sections: [
        { icon: "brightness", label: "Display" },
        { icon: "volume", label: "Sound" },
        { icon: "wifi", label: "Wi-Fi" },
        { icon: "bluetooth", label: "Bluetooth" },
        { icon: "map", label: "Map" },
        { icon: "memory", label: "System" },
        { icon: "info", label: "About" }
    ]
    function mmss(s) { return Math.floor(s / 60) + ":" + (s % 60 < 10 ? "0" : "") + s % 60 }

    // Scan for networks only while the Wi-Fi section is on screen.
    readonly property bool wifiShown: visible && section === 2
    onWifiShownChanged: if (typeof wifi !== "undefined") wifi.setScanning(wifiShown)

    // Check the Pi's health only while the System section is on screen.
    readonly property bool systemShown: visible && section === 5
    onSystemShownChanged: if (typeof system !== "undefined") system.setActive(systemShown)

    // ---- the section list ------------------------------------------------
    Item {
        id: list
        width: 232
        height: col.implicitHeight
        anchors { left: parent.left; top: parent.top }

        // One highlight that glides to the chosen row.
        Rectangle {
            y: page.section * (64 + col.spacing)
            width: list.width
            height: 64
            radius: Theme.radius
            color: Theme.panelHi
            border.width: Theme.border
            border.color: Theme.line
            Behavior on y { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }

            Rectangle {
                anchors { left: parent.left; leftMargin: 6; verticalCenter: parent.verticalCenter }
                width: 4
                height: parent.height - 26
                radius: 2
                color: Theme.accent
            }
        }

        Column {
            id: col
            width: list.width
            spacing: 8

            Repeater {
                model: page.sections
                Rectangle {
                    readonly property bool selected: page.section === index
                    width: list.width
                    height: 64
                    radius: Theme.radius
                    color: !selected && tap.pressed ? Theme.panel : "transparent"

                    Row {
                        anchors { left: parent.left; leftMargin: 24; verticalCenter: parent.verticalCenter }
                        spacing: 16
                        Icon {
                            anchors.verticalCenter: parent.verticalCenter
                            name: modelData.icon
                            size: 28
                            color: parent.parent.selected ? Theme.accent : Theme.textDim
                        }
                        Label {
                            anchors.verticalCenter: parent.verticalCenter
                            text: modelData.label
                            color: parent.parent.selected ? Theme.text : Theme.textDim
                            font.pixelSize: Theme.fontBody
                            font.weight: parent.parent.selected ? Font.DemiBold : Font.Normal
                        }
                    }
                    TapHandler { id: tap; onTapped: page.section = index }
                }
            }
        }
    }

    // ---- the chosen section ----------------------------------------------
    Loader {
        id: content
        anchors { left: list.right; leftMargin: Theme.gap; right: parent.right; top: parent.top; bottom: parent.bottom }
        sourceComponent: [displaySection, soundSection, wifiSection, bluetoothSection,
                          mapSection, systemSection, aboutSection][page.section]

        // A new section rises in; one section is alive at a time.
        transform: Translate { id: enterShift }
        onLoaded: enterAnim.restart()
        ParallelAnimation {
            id: enterAnim
            NumberAnimation { target: content; property: "opacity"; from: 0; to: 1; duration: 180; easing.type: Easing.OutCubic }
            NumberAnimation { target: enterShift; property: "y"; from: 16; to: 0; duration: 180; easing.type: Easing.OutCubic }
        }
    }

    // A scrolling column of cards, with a thin bar showing where you are.
    component Scroller: Flickable {
        id: flick
        default property alias cards: col.data
        contentHeight: col.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.VerticalFlick

        ColumnLayout {
            id: col
            width: flick.width - (flick.contentHeight > flick.height ? 14 : 0)
            spacing: Theme.gap
        }
        Rectangle {
            visible: flick.contentHeight > flick.height
            parent: flick
            anchors.right: parent.right
            y: flick.visibleArea.yPosition * flick.height
            width: 4
            height: flick.visibleArea.heightRatio * flick.height
            radius: 2
            color: Theme.line
        }
    }

    // A labelled row: what it is on the left, the control on the right.
    component SettingRow: RowLayout {
        property alias label: rowLabel.text
        Layout.fillWidth: true
        spacing: 16
        Label {
            id: rowLabel
            Layout.preferredWidth: 300
            font.pixelSize: Theme.fontBody
        }
    }

    // A minus, a bar, the percentage and a plus: one level the driver can nudge or drag.
    // The caller does the maths in its handlers; this only lays the row out.
    component LevelRow: RowLayout {
        property real value: 0
        property string percentText: ""
        property int segments: 20
        signal stepDown()
        signal stepUp()
        signal moved(real v)
        Layout.fillWidth: true
        spacing: 16
        IconButton { icon: "remove"; size: 60; onClicked: stepDown() }
        LevelBar {
            Layout.fillWidth: true
            segments: parent.segments
            value: parent.value
            onMoved: (v) => parent.moved(v)
        }
        Label {
            Layout.preferredWidth: 72
            Layout.leftMargin: 8
            horizontalAlignment: Text.AlignRight
            text: percentText
            font.family: Theme.numFont
            font.pixelSize: Theme.fontBody
            font.weight: Font.DemiBold
        }
        IconButton { icon: "add"; size: 60; onClicked: stepUp() }
    }

    // A static preview of one Style in its own colours, shape and numerals.
    // Plain rectangles and text only: nothing moves, nothing polls.
    component StyleSwatch: Rectangle {
        id: sw
        property string styleName: "amber"
        readonly property var t: Theme.dark ? Theme.styles[styleName]
            : Object.assign({}, Theme.styles[styleName], Theme.lightStyles[styleName] || {})
        readonly property bool picked: styleName === Theme.style
        objectName: "swatch_" + styleName
        Accessible.role: Accessible.Button
        Accessible.name: styleName + " style"
        width: 140
        height: 92
        color: tap.pressed ? t.panelHi : t.bg
        radius: t.radius
        border.width: t.border
        border.color: t.line

        // The selected ring, around the tile.
        Rectangle {
            objectName: "ring"
            visible: sw.picked
            anchors.fill: parent
            anchors.margins: -4
            z: -1
            color: "transparent"
            radius: sw.t.radius + 4
            border.width: 3
            border.color: Theme.accent
        }
        Rectangle {
            anchors.fill: parent
            anchors.margins: 10
            color: sw.t.panel
            radius: sw.t.radius
            border.width: sw.t.border
            border.color: sw.t.line
            Rectangle {
                width: 4
                radius: 2
                color: sw.t.accent
                anchors { left: parent.left; top: parent.top; bottom: parent.bottom; margins: 8 }
            }
            Text {
                anchors.centerIn: parent
                text: "88"
                color: sw.t.text
                font.family: sw.t.numFont
                font.italic: sw.t.numItalic
                font.weight: sw.t.numWeight
                font.pixelSize: 40
            }
            Rectangle {
                width: 10; height: 10; radius: 5
                color: sw.t.ok
                anchors { right: parent.right; top: parent.top; margins: 8 }
            }
        }
        TapHandler {
            id: tap
            onTapped: Theme.style = sw.styleName
        }
    }

    component Note: Label {
        Layout.fillWidth: true
        wrapMode: Text.WordWrap
        color: Theme.textDim
        font.pixelSize: Theme.fontSmall
    }

    // =====================================================================
    Component {
        id: displaySection
        Scroller {
            Section {
                Layout.fillWidth: true
                heading: (display.night ? "Brightness at night" : "Brightness in daylight")
                         + (display.hardware ? "" : " (software dim)")
                LevelRow {
                    value: display.brightness / 100
                    percentText: display.brightness + "%"
                    onStepDown: display.setBrightness(display.brightness - 10)
                    onStepUp: display.setBrightness(display.brightness + 10)
                    onMoved: (v) => display.setBrightness(Math.round(v * 100))
                }
                SettingRow {
                    label: "Screen"
                    TextButton {
                        icon: "power"
                        text: "Screen off"
                        onClicked: display.setScreenOff(true)
                    }
                    Label {
                        text: "Touch to wake"
                        color: Theme.textDim
                        font.pixelSize: Theme.fontSmall
                    }
                }
                SettingRow {
                    label: "Dim after sunset"
                    SegmentedControl {
                        options: [{ label: "On", value: true }, { label: "Off", value: false }]
                        current: display.autoNight
                        onPicked: (v) => display.setAutoNight(v)
                    }
                }
                Note {
                    readonly property string rise: display.sunrise > 0 ? Units.timeText(new Date(display.sunrise)) : ""
                    readonly property string set: display.sunset > 0 ? Units.timeText(new Date(display.sunset)) : ""
                    text: display.autoNight
                          ? "Daylight and night each keep their own level; the slider sets the one in use. Today the sun sets at " + set + " and rises at " + rise + " where the truck is."
                          : "One level all the time."
                }
            }
            Section {
                Layout.fillWidth: true
                heading: "Look"
                SettingRow {
                    label: "Appearance"
                    SegmentedControl {
                        options: [{ label: "Automatic", value: "auto" }, { label: "Light", value: "light" },
                                  { label: "Dark", value: "dark" }]
                        current: Units.appearance
                        onPicked: (v) => Units.appearance = v
                    }
                }
                Note { text: "Automatic is light while the sun is up and dark after it sets, where the truck is, for the whole dashboard and the map." }
                SettingRow {
                    label: "Style"
                    SegmentedControl {
                        options: Theme.styleNames.map(n => ({ label: n.charAt(0).toUpperCase() + n.slice(1), value: n }))
                        current: Theme.style
                        onPicked: (v) => Theme.style = v
                    }
                }
                Row {
                    objectName: "stylePreviews"
                    Layout.alignment: Qt.AlignRight
                    spacing: Theme.gap
                    Repeater {
                        model: Theme.styleNames
                        StyleSwatch { styleName: modelData }
                    }
                }
                SettingRow {
                    label: "Start-up animation"
                    SegmentedControl {
                        property bool on: typeof settings === "undefined" || String(settings.get("splash", "true")) === "true"
                        options: [{ label: "On", value: true }, { label: "Off", value: false }]
                        current: on
                        onPicked: (v) => { on = v; settings.set("splash", v ? "true" : "false") }
                    }
                }
            }
            Section {
                Layout.fillWidth: true
                heading: "Units and clock"
                SettingRow {
                    label: "Units"
                    SegmentedControl {
                        options: [{ label: "mph, °F, psi", value: false }, { label: "km/h, °C, bar", value: true }]
                        current: Units.metric
                        onPicked: (v) => Units.metric = v
                    }
                }
                SettingRow {
                    label: "Clock"
                    SegmentedControl {
                        options: [{ label: "12-hour", value: false }, { label: "24-hour", value: true }]
                        current: Units.clock24
                        onPicked: (v) => Units.clock24 = v
                    }
                }
            }
        }
    }

    // =====================================================================
    Component {
        id: soundSection
        Scroller {
            Section {
                Layout.fillWidth: true
                heading: "Equalizer"
                EqualizerPanel {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 400
                }
            }
            Section {
                Layout.fillWidth: true
                heading: "Loudest volume"
                Note { text: "The most the Pi will play, whatever the source. Handy with headphones: the volume slider still goes to 100, and 100 means this." }
                LevelRow {
                    segments: 14
                    value: (media.maxVolume - 30) / 70
                    percentText: media.maxVolume + "%"
                    onStepDown: media.setMaxVolume(media.maxVolume - 5)
                    onStepUp: media.setMaxVolume(media.maxVolume + 5)
                    onMoved: (v) => media.setMaxVolume(Math.round((30 + v * 70) / 5) * 5)
                }
            }
            Section {
                Layout.fillWidth: true
                heading: "Voice"
                SettingRow {
                    label: "Spoken directions"
                    SegmentedControl {
                        enabled: typeof voice !== "undefined" && voice.available
                        opacity: enabled ? 1 : 0.5
                        options: [{ label: "On", value: true }, { label: "Off", value: false }]
                        current: typeof voice !== "undefined" && voice.enabled
                        onPicked: (v) => voice.setEnabled(v)
                    }
                    TextButton {
                        visible: typeof voice !== "undefined" && voice.available
                        icon: "volume"
                        text: "Test"
                        onClicked: voice.test()
                    }
                }
                LevelRow {
                    visible: typeof voice !== "undefined" && voice.available
                    segments: 14
                    value: typeof voice !== "undefined" ? (voice.level - 30) / 70 : 0
                    percentText: (typeof voice !== "undefined" ? voice.level : 0) + "%"
                    onStepDown: voice.setLevel(voice.level - 5)
                    onStepUp: voice.setLevel(voice.level + 5)
                    onMoved: (v) => voice.setLevel(Math.round((30 + v * 70) / 5) * 5)
                }
                Note {
                    text: typeof voice !== "undefined" && voice.available
                          ? "Turn instructions are spoken over the music, which dips while they play. Their volume is their own: it follows the Loudest volume above, not the music volume or the source."
                          : "Run deploy/audio/install-voice.sh on the Pi once to add the voice (about 100 MB)."
                }
            }
            Section {
                Layout.fillWidth: true
                heading: "Spotify"
                Label {
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    font.pixelSize: Theme.fontBody
                    text: typeof spotify === "undefined" ? "Not set up on this Pi" : spotify.statusText
                }
                Note { text: "In the Spotify app on your phone, tap the devices icon and pick “" + (typeof spotify !== "undefined" && spotify.deviceName || "Baja") + "” to play through the truck. It only needs the same Wi-Fi as the Pi the first time." }
                Note {
                    text: typeof spotifyAccount === "undefined" ? ""
                          : spotifyAccount.linked ? "Your Spotify library is linked and stays linked after a restart."
                          : "To see your playlists here, open Music, Spotify, Playlists and scan the code."
                }
                ConfirmButton {
                    visible: typeof spotifyAccount !== "undefined" && spotifyAccount.linked
                    text: "Unlink library"
                    confirmText: "Tap to unlink"
                    onConfirmed: spotifyAccount.signOut()
                }
                SettingRow {
                    label: "Resume Spotify"
                    SegmentedControl {
                        options: [{ label: "On", value: true }, { label: "Off", value: false }]
                        current: media.spotifyResume
                        onPicked: (v) => media.setSpotifyResume(v)
                    }
                }
                Note { text: "Carry on playing Spotify after a restart or a lost connection" }
            }
        }
    }

    // =====================================================================
    Component {
        id: wifiSection
        Scroller {
            Section {
                Layout.fillWidth: true
                Row {
                    spacing: 12
                    readonly property bool known: typeof network !== "undefined" && network.checked
                    Rectangle {
                        anchors.verticalCenter: parent.verticalCenter
                        width: 14; height: 14; radius: 7
                        color: !parent.known ? Theme.textDim : network.online ? Theme.ok : Theme.warn
                    }
                    Label {
                        text: !parent.known ? "Checking the connection"
                              : network.online ? "Online"
                              : network.portal ? "Sign in to the network on your phone"
                              : (network.ip ? "Connected, but no internet" : "Offline")
                        font.pixelSize: Theme.fontTitle
                        font.weight: Font.DemiBold
                    }
                }
                Label {
                    objectName: "wifiMessage"
                    visible: wifi.message !== ""
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    font.pixelSize: Theme.fontBody
                    font.weight: Font.DemiBold
                    color: wifi.messageOk ? Theme.ok : Theme.warn
                    text: wifi.message
                }
                Label {
                    font.pixelSize: Theme.fontBody
                    color: Theme.textDim
                    text: wifi.tetherActive ? "Using " + wifi.tetherPhone + " over Bluetooth"
                          : network.ssid ? "On " + network.ssid + (network.ip ? ", " + network.ip : "")
                          : "Not on Wi-Fi"
                }
                Label {
                    visible: dataUse.available
                    font.pixelSize: Theme.fontBody
                    color: dataUse.overLimit ? Theme.warn : Theme.textDim
                    font.weight: dataUse.overLimit ? Font.DemiBold : Font.Normal
                    text: "Data this month: " + dataUse.text + (dataUse.limitGb > 0 ? " of " + dataUse.limitGb + " GB" : "")
                }
                Note {
                    visible: dataUse.available
                    text: "Counts all Wi-Fi and Bluetooth tether use, not only the phone's hotspot."
                }
                SettingRow {
                    visible: dataUse.available
                    label: "Data warning"
                    SegmentedControl {
                        options: [{ label: "Off", value: 0 }, { label: "5 GB", value: 5 }, { label: "10 GB", value: 10 },
                                  { label: "20 GB", value: 20 }, { label: "50 GB", value: 50 }]
                        current: dataUse.limitGb
                        onPicked: (v) => dataUse.setLimit(v)
                    }
                }
                Note {
                    visible: dataUse.available
                    text: "The line turns amber after this much in a month. It only warns; nothing is switched off."
                }
            }

            Section {
                Layout.fillWidth: true
                heading: "Networks nearby"

                Label {
                    visible: wifi.available && !wifi.canControl
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    color: Theme.accent
                    font.pixelSize: Theme.fontBody
                    text: "To join networks from here, run deploy/setup-pi.sh once on the Pi."
                }

                // The scan lands every 15 s (and `changed` also fires for other reasons).
                // Handing the Repeater the fresh list each time would rebuild every row
                // and disarm a half-done "Forget"; so keep one row per ssid and update
                // them in place.
                ListModel { id: netModel }
                Connections {
                    target: wifi
                    function onChanged() { netRows.sync(wifi.networks) }
                }
                Component.onCompleted: netRows.sync(wifi.networks)
                QtObject {
                    id: netRows
                    function indexOfSsid(ssid, from) {
                        for (var j = from; j < netModel.count; j++)
                            if (netModel.get(j).ssid === ssid) return j
                        return -1
                    }
                    function sync(nets) {
                        for (var i = 0; i < nets.length; i++) {
                            var j = indexOfSsid(nets[i].ssid, i)
                            if (j < 0) netModel.insert(i, nets[i])
                            else {
                                if (j !== i) netModel.move(j, i, 1)
                                netModel.set(i, nets[i])
                            }
                        }
                        if (netModel.count > nets.length)
                            netModel.remove(nets.length, netModel.count - nets.length)
                    }
                }

                Repeater {
                    model: netModel
                    Rectangle {
                        id: netRow
                        readonly property bool joining: wifi.busy === model.ssid
                        Layout.fillWidth: true
                        Layout.preferredHeight: 64
                        radius: Theme.radius
                        color: model.active ? Theme.panelHi : (rowTap.pressed ? Theme.panelHi : "transparent")
                        border.width: model.active ? Theme.border : 0
                        border.color: Theme.line

                        SignalBars {
                            id: bars
                            anchors { left: parent.left; leftMargin: 16; verticalCenter: parent.verticalCenter }
                            signal: model.signal
                            lit: model.active ? Theme.accent : Theme.text
                        }
                        Label {
                            anchors { left: bars.right; leftMargin: 18; right: status.left; rightMargin: 12; verticalCenter: parent.verticalCenter }
                            text: model.ssid
                            elide: Text.ElideRight
                            font.pixelSize: Theme.fontBody
                            font.weight: model.active ? Font.DemiBold : Font.Normal
                        }
                        Row {
                            id: status
                            anchors { right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter }
                            spacing: 14
                            Label {
                                anchors.verticalCenter: parent.verticalCenter
                                visible: text !== ""
                                text: netRow.joining ? "Joining" : model.active ? "Connected" : model.saved ? "Saved" : ""
                                color: model.active ? Theme.accent : Theme.textDim
                                font.pixelSize: Theme.fontSmall
                                font.weight: Font.DemiBold
                            }
                            Icon {
                                anchors.verticalCenter: parent.verticalCenter
                                visible: model.secure
                                name: "lock"
                                size: 22
                                color: Theme.textDim
                            }
                            ConfirmButton {
                                id: forgetBtn
                                visible: model.saved && wifi.canControl
                                implicitHeight: 56
                                text: "Forget"
                                confirmText: "Sure?"
                                onConfirmed: wifi.forget(model.ssid)
                            }
                        }
                        TapHandler {
                            id: rowTap
                            enabled: !model.active && wifi.canControl && wifi.busy === ""
                            onTapped: (eventPoint) => {
                                // A tap on Forget reaches this handler too; it is not a tap on the row.
                                if (forgetBtn.visible && forgetBtn.contains(forgetBtn.mapFromItem(netRow, eventPoint.position))) return
                                if (model.saved || !model.secure) wifi.join(model.ssid, "")
                                else joinSheet.open(model.ssid)
                            }
                        }
                    }
                }
                // A network that doesn't broadcast its name: type it in.
                Rectangle {
                    visible: wifi.available && wifi.canControl
                    Layout.fillWidth: true
                    Layout.preferredHeight: 64
                    radius: Theme.radius
                    color: otherTap.pressed ? Theme.panelHi : "transparent"
                    Label {
                        anchors { left: parent.left; leftMargin: 16; verticalCenter: parent.verticalCenter }
                        text: "Other network…"
                        font.pixelSize: Theme.fontBody
                    }
                    TapHandler {
                        id: otherTap
                        enabled: wifi.busy === ""
                        onTapped: joinSheet.openHidden()
                    }
                }
                Note {
                    visible: wifi.available
                    text: wifi.networks.length === 0 ? "Looking for networks"
                          : "For your phone's hotspot: turn on Personal Hotspot with Maximize Compatibility on, keep that screen open, then tap the phone's name here. After that the Pi joins it by itself."
                }
                Note {
                    visible: !wifi.available
                    text: "Wi-Fi is managed by the computer this is running on."
                }
            }

            // Saved networks the scan can't see (an old hotspot, home): the Pi keeps
            // retrying them, so give them a way out.
            Section {
                Layout.fillWidth: true
                heading: "Saved, not in range"
                visible: wifi.canControl && wifi.savedElsewhere.length > 0

                Repeater {
                    model: wifi.savedElsewhere
                    delegate: RowLayout {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 64
                        spacing: 12
                        Label {
                            Layout.fillWidth: true
                            elide: Text.ElideRight
                            text: modelData.ssid
                            font.pixelSize: Theme.fontBody
                        }
                        Label {
                            color: Theme.textDim
                            text: "Not in range"
                            font.pixelSize: Theme.fontSmall
                        }
                        ConfirmButton {
                            Layout.preferredHeight: 56
                            text: "Forget"
                            confirmText: "Sure?"
                            onConfirmed: wifi.forget(modelData.ssid)
                        }
                    }
                }
            }

            Section {
                Layout.fillWidth: true
                heading: "Phone as backup"
                Note {
                    text: wifi.tetherPhone !== ""
                          ? "When there's no Wi-Fi for a minute, use " + wifi.tetherPhone + " over Bluetooth for internet (Personal Hotspot needs to be on). It lets go again once Wi-Fi is back."
                          : "Pair your phone under Bluetooth first; then it can be the backup connection."
                }
                SegmentedControl {
                    enabled: wifi.tetherPhone !== ""
                    opacity: enabled ? 1 : 0.5
                    options: [{ label: "On", value: true }, { label: "Off", value: false }]
                    current: wifi.tethering
                    onPicked: (v) => wifi.setTethering(v)
                }
            }
        }
    }

    // =====================================================================
    Component {
        id: bluetoothSection
        Scroller {
            Section {
                visible: !bluetooth.agentOk && bluetooth.agentProblem !== ""
                Layout.fillWidth: true
                heading: "Pairing can't be confirmed on this screen"
                Label {
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    color: Theme.warn
                    font.pixelSize: Theme.fontBody
                    text: "A new phone may not pair, or may pair without asking and then be refused. Don't rely on Pair phone until this clears. Phones already paired still connect."
                }
                Note { text: bluetooth.agentProblem }
                Note { text: "It keeps trying by itself. If this stays, restart Baja OS and check bluetooth.service on the Pi." }
            }

            Section {
                id: btCard
                Layout.fillWidth: true
                heading: "Phone"
                property int secondsLeft: 0
                Timer {
                    interval: 1000; repeat: true; triggeredOnStart: true
                    running: bluetooth.pairing
                    onTriggered: btCard.secondsLeft = bluetooth.pairingSecondsLeft
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 14
                    Icon {
                        name: "bluetooth"
                        size: 30
                        color: bluetooth.deviceName !== "" || bluetooth.pairing ? Theme.accent : Theme.textDim
                    }
                    Label {
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                        font.pixelSize: Theme.fontBody
                        text: !bluetooth.available ? "Bluetooth isn't available here"
                              : !bluetooth.adapterPresent ? "Bluetooth is off"
                              : bluetooth.pairing ? "Visible as “Baja OS”: pair from your phone (" + page.mmss(btCard.secondsLeft) + ")"
                              : bluetooth.deviceName !== "" ? "Connected: " + bluetooth.deviceName
                              : "No phone connected"
                    }
                    TextButton {
                        visible: bluetooth.available && bluetooth.adapterPresent
                        primary: !bluetooth.pairing
                        text: bluetooth.pairing ? "Stop pairing" : "Pair phone"
                        onClicked: bluetooth.setPairing(!bluetooth.pairing)
                    }
                }
                Note {
                    text: "Pairing stays open for two minutes. On the phone, open Bluetooth settings and pick “Baja OS”, then tap Pair on this screen when the code matches the phone's (some phones show none). Once paired, the phone reconnects by itself and its music plays through the truck, with track info and volume on this screen."
                }
            }

            Section {
                visible: bluetooth.available && bluetooth.paired.length > 0
                Layout.fillWidth: true
                heading: "Paired"
                Repeater {
                    model: bluetooth.paired
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 14
                        Icon {
                            name: "phone"
                            size: 28
                            color: modelData.connected ? Theme.accent : Theme.textDim
                        }
                        Column {
                            Layout.fillWidth: true
                            Label {
                                width: parent.width
                                elide: Text.ElideRight
                                textFormat: Text.PlainText
                                text: modelData.name
                                font.pixelSize: Theme.fontBody
                                font.weight: modelData.connected ? Font.DemiBold : Font.Normal
                            }
                            Label {
                                width: parent.width
                                elide: Text.ElideRight
                                text: (modelData.connected ? "Connected" : "Not connected")
                                      + (modelData.pairedOn !== "" ? " · Paired " + modelData.pairedOn
                                         : modelData.trusted ? " · Paired before the update" : "")
                                color: modelData.connected ? Theme.accent : Theme.textDim
                                font.pixelSize: Theme.fontSmall
                            }
                            Label {
                                visible: !modelData.trusted
                                text: "Not accepted on this screen"
                                color: Theme.warn
                                font.pixelSize: Theme.fontSmall
                            }
                        }
                        TextButton {
                            text: modelData.connected ? "Disconnect" : "Connect"
                            onClicked: modelData.connected ? bluetooth.disconnectDevice(modelData.path)
                                                           : bluetooth.connectDevice(modelData.path)
                        }
                        ConfirmButton {
                            icon: "delete"
                            text: "Forget"
                            confirmText: "Sure?"
                            danger: true
                            onConfirmed: bluetooth.forgetDevice(modelData.path)
                        }
                    }
                }
                Note { text: "Forgetting a phone means pairing it again to use it here." }
            }
        }
    }

    // =====================================================================
    Component {
        id: mapSection
        Scroller {
            Section {
                id: mapCard
                Layout.fillWidth: true
                heading: "Offline map"
                // The update cuts a fresh extract of the same area, so it's about
                // the size of the map on the Pi (130 MB for the first Seattle one).
                readonly property int downloadMb: maps.ready ? Math.max(1, Math.round(maps.sizeMb)) : 130
                // An iPhone hotspot hands out 172.20.10.x addresses: that's the phone's data.
                readonly property bool hotspot: network.ip.startsWith("172.20.10.")
                property bool asking: false
                onHotspotChanged: asking = false
                readonly property string built: typeof maps === "undefined" || maps.build.length !== 8 ? ""
                    : new Date(+maps.build.slice(0, 4), +maps.build.slice(4, 6) - 1, +maps.build.slice(6))
                          .toLocaleDateString(Qt.locale("en_GB"), "d MMMM yyyy")
                Label {
                    font.pixelSize: Theme.fontTitle
                    font.weight: Font.DemiBold
                    text: maps.ready ? maps.region : "No map installed"
                }
                Label {
                    visible: maps.ready
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    color: Theme.textDim
                    font.pixelSize: Theme.fontBody
                    text: "OpenStreetMap data from " + mapCard.built + ", " + Math.round(maps.sizeMb) + " MB on the Pi. Works with no signal."
                }
                RowLayout {
                    spacing: 16
                    TextButton {
                        icon: "refresh"
                        text: maps.ready ? "Update map" : "Download map"
                        enabled: !maps.updating && network.online
                        onClicked: mapCard.hotspot ? mapCard.asking = true : maps.update()
                    }
                    Label {
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                        color: Theme.textDim
                        font.pixelSize: Theme.fontBody
                        text: maps.updating || maps.updateMessage !== "" ? maps.updateMessage
                              : network.online ? "Downloads about " + mapCard.downloadMb + " MB" : "Needs internet"
                    }
                }
                // On the phone's hotspot the download comes out of its data plan.
                RowLayout {
                    visible: mapCard.asking && mapCard.hotspot && !maps.updating
                    Layout.fillWidth: true
                    spacing: 16
                    TextButton {
                        icon: "refresh"
                        text: "Download anyway"
                        enabled: network.online
                        onClicked: { mapCard.asking = false; maps.update() }
                    }
                    TextButton {
                        text: "Not now"
                        onClicked: mapCard.asking = false
                    }
                    Label {
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                        color: Theme.textDim
                        font.pixelSize: Theme.fontBody
                        text: "You're on your phone's hotspot, so this uses about " + mapCard.downloadMb + " MB of its data."
                    }
                }
            }
            Section {
                id: sendCard
                Layout.fillWidth: true
                heading: "Send from your phone"
                readonly property bool has: typeof phone !== "undefined"
                // On an iPhone hotspot the Pi also answers on a fixed address.
                readonly property string ip: typeof network === "undefined" || !network.ip ? ""
                                             : network.ip.indexOf("172.20.10.") === 0 ? "172.20.10.14" : network.ip
                readonly property var last: has ? phone.lastSent : ({})
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 24
                    Image {
                        visible: sendCard.ip !== "" && sendCard.has
                        Layout.preferredWidth: 220
                        Layout.preferredHeight: 220
                        // phone.revision goes up with Reset link: a new code to draw.
                        source: visible ? phone.qrImage(sendCard.ip, phone.revision) : ""
                        smooth: false
                        fillMode: Image.PreserveAspectFit
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 10
                        Label {
                            Layout.fillWidth: true
                            wrapMode: Text.WordWrap
                            font.pixelSize: Theme.fontBody
                            text: sendCard.ip === "" ? "Connect to Wi-Fi or your phone's hotspot first."
                                  : "Scan this with the iPhone camera."
                        }
                        Note {
                            text: "It opens a page where you can paste a link from Apple Maps or Google Maps, an address or a place, and send it here. The page also shows how to add a Send to Baja shortcut to the Share button, so you can send a place straight from Maps. It arrives on the Maps page, ready for Go."
                        }
                        Note {
                            visible: sendCard.last.name !== undefined
                            textFormat: Text.PlainText      // the name is whatever the phone sent
                            text: sendCard.last.name === undefined ? ""
                                  : "Last place: " + sendCard.last.name + ", from " + sendCard.last.ip
                                    + " at " + Units.timeText(new Date(sendCard.last.at))
                        }
                    }
                }
                RowLayout {
                    visible: sendCard.has
                    Layout.fillWidth: true
                    spacing: 16
                    ConfirmButton {
                        icon: "refresh"
                        text: "Reset link"
                        confirmText: "Tap to reset"
                        danger: true
                        onConfirmed: phone.resetToken()
                    }
                    Note {
                        text: "Makes a new code. Phones that scanned the old one, and the Shortcut, stop working: scan the new code, and copy the new token from its page into the Shortcut."
                    }
                }
            }
            Section {
                id: gpsSection
                Layout.fillWidth: true
                heading: "GPS"
                readonly property bool has: typeof gps !== "undefined"
                Row {
                    spacing: 12
                    Rectangle {
                        anchors.verticalCenter: parent.verticalCenter
                        width: 14; height: 14; radius: 7
                        color: !gpsSection.has ? Theme.textDim
                               : gps.realFix ? Theme.ok
                               : gps.receiverConnected ? Theme.accent : Theme.textDim
                    }
                    Label {
                        font.pixelSize: Theme.fontBody
                        text: !gpsSection.has ? "Not available"
                              : gps.realFix ? "Position found" + (gps.satellites > 0 ? ", " + gps.satellites + " satellites" : "")
                              : gps.stale && gps.receiverConnected ? "Lost the signal"
                              : gps.receiverConnected ? "Looking for satellites" + (gps.satellitesInView > 0 ? ": " + gps.satellitesInView + " in view" : "")
                              : "No receiver"
                    }
                }
                Note {
                    text: !gpsSection.has ? ""
                          : gps.realFix ? "The map and directions follow the truck's real position."
                          : gps.stale ? "The map holds the truck's last position, and directions wait, until the receiver has a position again."
                          : (gps.receiverConnected ? "The receiver needs a view of the sky: on the dash or by a window, not deep indoors. The first fix can take a minute or two."
                                                   : "Plug the GPS receiver into a USB port.")
                            + (gps.source === "demo" ? " Until then the map follows a practice drive around Seattle." : "")
                }
            }
            Section {
                Layout.fillWidth: true
                heading: "Route options"
                Repeater {
                    model: [{ label: "Avoid ferries", key: "avoidFerries" },
                            { label: "Avoid highways", key: "avoidHighways" },
                            { label: "Avoid tolls", key: "avoidTolls" }]
                    SettingRow {
                        required property var modelData
                        label: modelData.label
                        SegmentedControl {
                            options: [{ label: "On", value: true }, { label: "Off", value: false }]
                            current: typeof routing !== "undefined" && (modelData.key === "avoidFerries" ? routing.avoidFerries
                                     : modelData.key === "avoidHighways" ? routing.avoidHighways : routing.avoidTolls)
                            onPicked: (v) => routing.setAvoid(modelData.key, v)
                        }
                    }
                }
                // Guidance has no other place to say a change didn't work.
                Note {
                    readonly property bool shown: typeof routing !== "undefined" && (routing.active || routing.previewing)
                    text: shown && routing.computing ? "Finding a route with these options"
                          : shown && routing.error !== "" ? routing.error + ". The route on screen hasn't changed."
                          : "Used for every new route. Changing one while a route is showing works it out again."
                }
            }
            Section {
                Layout.fillWidth: true
                heading: "Directions"
                Row {
                    spacing: 12
                    Rectangle {
                        anchors.verticalCenter: parent.verticalCenter
                        width: 14; height: 14; radius: 7
                        color: typeof routing !== "undefined" && routing.available ? Theme.ok : Theme.textDim
                    }
                    Label {
                        font.pixelSize: Theme.fontBody
                        text: typeof routing !== "undefined" && routing.available
                              ? "Ready: turn-by-turn directions with no signal"
                              : "Not installed"
                    }
                }
                Note {
                    text: typeof routing !== "undefined" && routing.available
                          ? "Search for a place on the Maps page and tap Go. Directions come from Valhalla on the Pi, using OpenStreetMap roads for Washington."
                          : "Run deploy/maps/install-routing.sh on the Pi once: it downloads Washington's roads (365 MB) and builds them for directions, which takes about half an hour."
                }
            }
        }
    }

    // =====================================================================
    Component {
        id: systemSection
        Scroller {
            Section {
                Layout.fillWidth: true
                heading: "Health"
                GridLayout {
                    Layout.fillWidth: true
                    columns: 3
                    rowSpacing: 18
                    columnSpacing: 16
                    Readout {
                        Layout.fillWidth: true; Layout.preferredWidth: 1
                        label: "Temperature"
                        value: system.temp < 0 ? "–" : Math.round(Units.temp(system.temp * 9 / 5 + 32))
                        unit: system.temp < 0 ? "" : Units.tempUnit
                        warning: system.temp > 75
                    }
                    Readout {
                        Layout.fillWidth: true; Layout.preferredWidth: 1
                        label: "Fan"
                        value: system.fan < 0 ? "–" : system.fan
                        unit: system.fan < 0 ? "" : "rpm"
                    }
                    Readout {
                        Layout.fillWidth: true; Layout.preferredWidth: 1
                        label: "Uptime"
                        value: system.uptime || "–"
                        unit: ""
                    }
                    Readout {
                        Layout.fillWidth: true; Layout.preferredWidth: 1
                        label: "Memory used"
                        value: system.memTotal > 0 ? (system.memUsed / 1024).toFixed(1) : "–"
                        unit: system.memTotal > 0 ? "of " + Math.round(system.memTotal / 1024) + " GB" : ""
                    }
                    Readout {
                        Layout.fillWidth: true; Layout.preferredWidth: 1
                        label: "Storage free"
                        value: system.diskTotal > 0 ? Math.round(system.diskFree) : "–"
                        unit: system.diskTotal > 0 ? "of " + Math.round(system.diskTotal) + " GB" : ""
                    }
                    Item { Layout.fillWidth: true; Layout.preferredWidth: 1 }
                }
                Label {
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    font.pixelSize: Theme.fontBody
                    color: system.power !== "" || system.errors > 0 ? Theme.warn : Theme.textDim
                    text: (system.power !== "" ? system.power : "Power supply and temperature are fine")
                          + (system.errors > 0 ? " · " + system.errors + (system.errors === 1 ? " error" : " errors") + " since start" : "")
                }
                Label {
                    Layout.fillWidth: true
                    visible: powerLog.supply >= 0
                    font.pixelSize: Theme.fontBody
                    color: powerLog.lowest < 4.8 ? Theme.warn : Theme.textDim
                    text: "Pi supply " + powerLog.supply.toFixed(2) + " V, lowest " + powerLog.lowest.toFixed(2) + " V"
                }
            }

            Section {
                Layout.fillWidth: true
                heading: "Restart and power"
                RowLayout {
                    spacing: 14
                    ConfirmButton { icon: "refresh"; text: "Restart dashboard"; confirmText: "Tap to restart"; enabled: !updater.busy; onConfirmed: system.restartDashboard() }
                    ConfirmButton { text: "Reboot"; confirmText: "Tap to reboot"; enabled: system.canPower && !updater.updating; onConfirmed: system.reboot() }
                    ConfirmButton { icon: "power"; text: "Shut down"; confirmText: "Tap to shut down"; danger: true; enabled: system.canPower && !updater.updating; onConfirmed: system.powerOff() }
                }
                Label {
                    visible: system.powerError !== ""
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    color: Theme.warn
                    font.pixelSize: Theme.fontSmall
                    text: "Couldn't do that: " + system.powerError
                }
                Note {
                    visible: !system.canPower
                    text: "To reboot or shut down, from here or with the key, run deploy/setup-pi.sh once on the Pi."
                }
                SettingRow {
                    label: "Shut down with key"
                    SegmentedControl {
                        // Off can always be picked; On needs the Pi to be allowed to shut down.
                        enabled: system.canPower || keyOff.enabled
                        opacity: enabled ? 1 : 0.5
                        options: [{ label: "On", value: true }, { label: "Off", value: false }]
                        current: keyOff.enabled
                        onPicked: (v) => keyOff.setEnabled(v)
                    }
                }
                Note {
                    text: keyOff.enabled
                          ? "When the truck is turned off (it stops answering the OBD adapter), the Pi counts down 25 s and shuts down, inside the power relay's hold time. Keep on stops it."
                          : "Turn this on once the Pi runs through the power relay. On any other power, a shut-down Pi stays off until it's unplugged and plugged back in."
                }
            }

            Section {
                Layout.fillWidth: true
                heading: "Software update"
                RowLayout {
                    spacing: 14
                    TextButton { icon: "refresh"; text: "Check for updates"; enabled: !updater.busy; onClicked: updater.check() }
                    TextButton { text: "Update"; enabled: updater.canUpdate; onClicked: updater.update() }
                }
                Label {
                    visible: updater.message !== ""
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    font.pixelSize: Theme.fontBody
                    color: updater.state === "failed" ? Theme.warn : Theme.textDim
                    text: updater.message
                }
                Repeater {
                    model: updater.commits
                    Label {
                        Layout.fillWidth: true
                        elide: Text.ElideRight
                        font.pixelSize: Theme.fontSmall
                        color: Theme.textDim
                        text: "· " + modelData
                    }
                }
                Label {
                    visible: updater.count > updater.commits.length
                    font.pixelSize: Theme.fontSmall
                    color: Theme.textDim
                    text: "and " + (updater.count - updater.commits.length) + " more"
                }
                Note { text: "Update pulls what Check found and restarts the dashboard. It won't run while driving, while directions are on, or if files here were changed over SSH." }
            }
        }
    }

    // A key that needs a second tap within a few seconds, for actions that
    // can't be undone.
    component ConfirmButton: TextButton {
        id: cb
        property string confirmText
        property string plainText
        signal confirmed()
        // Wide enough for either text, so arming never resizes the key or
        // shoves its neighbours along the row.
        implicitWidth: Math.max(plainProbe.implicitWidth, confirmProbe.implicitWidth) + (icon !== "" ? 34 : 0) + 40
        Label { id: plainProbe; visible: false; text: cb.plainText; font.pixelSize: Theme.fontBody - 2; font.weight: Font.DemiBold }
        Label { id: confirmProbe; visible: false; text: cb.confirmText; font.pixelSize: Theme.fontBody - 2; font.weight: Font.DemiBold }
        Component.onCompleted: plainText = text
        onArmedChanged: text = armed ? confirmText : plainText
        onClicked: {
            if (armed) { armed = false; confirmed() }
            else { armed = true; disarm.restart() }
        }
        Timer { id: disarm; interval: 4000; onTriggered: cb.armed = false }
    }

    // =====================================================================
    Component {
        id: aboutSection
        Scroller {
            Section {
                Layout.fillWidth: true
                Label { text: "Baja OS"; font.pixelSize: Theme.fontHero; font.weight: Font.DemiBold }
                Label { text: "The dashboard for a 2005 Subaru Baja Turbo"; color: Theme.textDim; font.pixelSize: Theme.fontBody }
                Label {
                    font.pixelSize: Theme.fontBody
                    text: "Baja OS " + (system.version || "(unknown version)")
                }
                Label {
                    visible: system.restarts >= 0
                    color: system.restarts >= 3 ? Theme.warn : Theme.textDim
                    font.pixelSize: Theme.fontBody
                    text: "Restarted " + system.restarts + (system.restarts === 1 ? " time" : " times")
                          + " since the Pi booted"
                }
                Label {
                    visible: network.ip !== ""
                    color: Theme.textDim
                    font.pixelSize: Theme.fontBody
                    text: "ssh " + network.user + "@" + network.ip
                }
                Label {
                    visible: typeof vehicle !== "undefined" && vehicle.simulated
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    color: Theme.accent
                    font.pixelSize: Theme.fontBody
                    text: "Gauges show simulated data until the car first answers over the OBD-II adapter (key on)."
                }
            }
            Section {
                Layout.fillWidth: true
                heading: "Made with"
                Repeater {
                    model: [
                        "Map data © OpenStreetMap contributors (ODbL)",
                        "Map tiles from Protomaps, drawn with MapLibre GL JS",
                        "Music from Spotify, played by Spotify's Soloist",
                        "Qt 6 and PyQt6; icons from Material Design (Apache 2.0)",
                        "Type: URW Gothic"
                    ]
                    Label {
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                        font.pixelSize: Theme.fontBody
                        color: Theme.textDim
                        text: modelData
                    }
                }
            }
        }
    }

    // A saved network that now wants a different password: ask for it.
    Connections {
        target: wifi
        function onPasswordNeeded(ssid) {
            joinSheet.open(ssid)
            joinSheet.note = "That password didn't work. Check it and try again."
        }
    }

    // ---- joining a Wi-Fi network: password and keyboard --------------------
    Rectangle {
        id: joinSheet
        objectName: "joinSheet"
        property string ssid: ""
        property string password: ""
        property bool reveal: false
        property bool hidden: false      // a network typed in by hand
        property bool naming: false      // ...and its name is still being typed
        property string note: ""         // why the sheet is open again, e.g. a wrong password
        property bool lastShown: false   // the newest character shows for a moment, like a phone
        // Only runs for a moment after a key press, so nothing ticks while idle.
        Timer { id: lastTimer; interval: 900; onTriggered: joinSheet.lastShown = false }
        function open(name) { ssid = name; password = ""; reveal = false; hidden = false; naming = false; note = ""; lastShown = false; lastTimer.stop() }
        function openHidden() { ssid = ""; password = ""; reveal = false; hidden = true; naming = true; note = ""; lastShown = false; lastTimer.stop() }
        function close() { ssid = ""; password = ""; hidden = false; naming = false; note = ""; lastShown = false; lastTimer.stop() }
        // The password as dots, with the newest character shown while lastShown.
        function dots() {
            var n = password.length
            return lastShown ? "•".repeat(n - 1) + password.charAt(n - 1) : "•".repeat(n)
        }

        anchors.fill: parent
        visible: ssid !== "" || naming
        color: Theme.bg
        // Swallow taps so nothing underneath reacts.
        MouseArea { anchors.fill: parent }

        ColumnLayout {
            anchors.fill: parent
            spacing: Theme.gap

            RowLayout {
                Layout.fillWidth: true
                spacing: 14
                Label {
                    Layout.fillWidth: true
                    text: joinSheet.naming ? "Other network" : "Join “" + joinSheet.ssid + "”"
                    elide: Text.ElideRight
                    font.pixelSize: Theme.fontTitle
                    font.weight: Font.DemiBold
                }
                TextButton { text: "Cancel"; onClicked: joinSheet.close() }
            }

            Label {
                objectName: "joinNote"
                visible: joinSheet.note !== ""
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                color: Theme.warn
                font.pixelSize: Theme.fontBody
                font.weight: Font.DemiBold
                text: joinSheet.note
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 14
                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 64
                    radius: Theme.radius
                    color: Theme.panel
                    border.width: Theme.border
                    border.color: Theme.accent
                    Label {
                        id: field
                        objectName: "joinField"
                        anchors { left: parent.left; leftMargin: 18; verticalCenter: parent.verticalCenter }
                        width: Math.min(implicitWidth, parent.width - 50)
                        clip: true
                        horizontalAlignment: implicitWidth > width ? Text.AlignRight : Text.AlignLeft
                        text: joinSheet.naming ? joinSheet.ssid
                              : joinSheet.password === "" ? ""
                              : joinSheet.reveal ? joinSheet.password : joinSheet.dots()
                        font.pixelSize: Theme.fontTitle
                    }
                    Label {
                        objectName: "joinHint"
                        visible: joinSheet.naming ? joinSheet.ssid === ""
                                 : joinSheet.password === "" || joinSheet.password.length < 8   // 1-7: say why Join is off
                        anchors.verticalCenter: parent.verticalCenter
                        // Beside the typed dots, not over them.
                        x: !joinSheet.naming && joinSheet.password.length > 0 ? parent.width - width - 18 : 22
                        text: joinSheet.naming ? "Network name"
                              : joinSheet.password.length > 0 ? "8 or more characters"
                              : joinSheet.hidden ? "Password (empty if open)" : "Password"
                        color: Theme.textDim
                        font.pixelSize: Theme.fontBody
                    }
                    // Blinking caret.
                    Rectangle {
                        x: field.x + field.width + 3
                        anchors.verticalCenter: parent.verticalCenter
                        width: 2
                        height: 34
                        color: Theme.accent
                        SequentialAnimation on opacity {
                            running: joinSheet.visible
                            loops: Animation.Infinite
                            NumberAnimation { to: 0; duration: 500; easing.type: Easing.InOutQuad }
                            NumberAnimation { to: 1; duration: 500; easing.type: Easing.InOutQuad }
                        }
                    }
                }
                IconButton {
                    visible: !joinSheet.naming
                    size: 64
                    icon: joinSheet.reveal ? "visibility_off" : "visibility"
                    onClicked: joinSheet.reveal = !joinSheet.reveal
                }
            }

            Keyboard {
                objectName: "joinKeyboard"
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.maximumHeight: 440
                doneLabel: joinSheet.naming ? "Next" : "Join"
                doneEnabled: joinSheet.naming ? joinSheet.ssid.length > 0
                             : joinSheet.password.length >= 8      // WPA passwords are 8+
                                || (joinSheet.hidden && joinSheet.password.length === 0)
                onTyped: (ch) => {
                    if (joinSheet.naming) joinSheet.ssid += ch
                    else {
                        joinSheet.password += ch
                        joinSheet.lastShown = true
                        lastTimer.restart()
                    }
                }
                onBackspace: {
                    joinSheet.lastShown = false
                    lastTimer.stop()
                    if (joinSheet.naming) joinSheet.ssid = joinSheet.ssid.slice(0, -1)
                    else joinSheet.password = joinSheet.password.slice(0, -1)
                }
                onDone: {
                    if (joinSheet.naming) { joinSheet.naming = false; return }
                    if (joinSheet.hidden) wifi.joinHidden(joinSheet.ssid, joinSheet.password)
                    else wifi.join(joinSheet.ssid, joinSheet.password)
                    joinSheet.close()
                }
            }
        }
    }
}
