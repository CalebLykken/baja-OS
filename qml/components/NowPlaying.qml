import QtQuick
import QtQuick.Layouts

// The Home screen's music card: the cover as a framed print beside where the
// music comes from, title and artist; progress and the transport keys run
// across underneath. No heading: a song explains itself. Tap the cover to
// open Music. With no music on the Pi (and nothing from the phone or
// Spotify) it says "Nothing playing", with the keys dimmed.
Card {
    id: np
    signal openMusic()

    readonly property bool idle: media.source === "local" && media.title === ""

    // What the labels show. They trail the live track by the length of the
    // slide, so the words can change while they are out of sight.
    property string shownTitle: ""
    property string shownArtist: ""
    property bool seeded: false
    // The title the running slide is heading to.
    property string slideTarget: ""
    readonly property string liveTitle: np.idle ? (media.scanning ? "Reading your music" : "Nothing playing") : media.title
    readonly property string liveArtist: media.artist

    Component.onCompleted: {
        shownTitle = liveTitle
        shownArtist = liveArtist
        seeded = true
    }
    // Title and artist come from one notify signal, so both change handlers
    // fire for one track change. Deferred on purpose: one emission, one
    // decision, made after both values have settled.
    onLiveTitleChanged: Qt.callLater(np.trackChanged)
    onLiveArtistChanged: Qt.callLater(np.trackChanged)

    // A new song slides the words out to the left, swaps them while they
    // are invisible, and slides them back in from the right (a card being
    // moved along, pairing with the cover's crossfade). A skip mid-slide
    // settles the words at once and starts over, so they never stay
    // half-faded or stale. Only the title starts the slide: an artist
    // change alone just updates in place.
    function trackChanged() {
        if (!seeded) return
        if (liveTitle === shownTitle) {
            shownArtist = liveArtist
            return
        }
        // Already sliding to this title: the midpoint script reads the live
        // values, so there is nothing to restart.
        if (slide.running && liveTitle === slideTarget) return
        if (slide.running) {
            slide.stop()
            words.opacity = 1
            shift.x = 0
            shownTitle = liveTitle
            shownArtist = liveArtist
        }
        slideTarget = liveTitle
        slide.start()
    }

    SequentialAnimation {
        id: slide
        ParallelAnimation {
            NumberAnimation { target: words; property: "opacity"; from: 1; to: 0; duration: 120; easing.type: Easing.InCubic }
            NumberAnimation { target: shift; property: "x"; from: 0; to: -28; duration: 120; easing.type: Easing.InCubic }
        }
        ScriptAction {
            script: {
                np.shownTitle = np.liveTitle
                np.shownArtist = np.liveArtist
                shift.x = 28
            }
        }
        ParallelAnimation {
            NumberAnimation { target: words; property: "opacity"; from: 0; to: 1; duration: 200; easing.type: Easing.OutCubic }
            NumberAnimation { target: shift; property: "x"; from: 28; to: 0; duration: 200; easing.type: Easing.OutCubic }
        }
    }

    function mmss(s) {
        var m = Math.floor(s / 60), r = s % 60
        return m + ":" + (r < 10 ? "0" : "") + r
    }

    ColumnLayout {
        anchors { fill: parent; margins: 20 }
        spacing: 6

        // A plain Item, so the cover can size itself from the space the
        // column gives this row without a layout loop.
        Item {
            id: top
            Layout.fillWidth: true
            Layout.fillHeight: true

            AlbumArt {
                id: art
                // Leave room for the print's offset shadow below and right.
                width: Math.min(top.height - 12, top.width * 0.52)
                height: width
                anchors { left: parent.left; verticalCenter: parent.verticalCenter; verticalCenterOffset: -4 }
                source: media.artCard
                placeholder: media.source === "phone" ? "phone" : "music"
                TapHandler { onTapped: np.openMusic() }
            }

            ColumnLayout {
                id: words
                // Translate moves the words without touching the anchors.
                transform: Translate { id: shift }
                anchors { left: art.right; leftMargin: 26; right: parent.right; verticalCenter: art.verticalCenter }
                spacing: 6

                SourceBadge { Layout.fillWidth: true }
                Label {
                    Layout.fillWidth: true
                    Layout.topMargin: 2
                    text: np.shownTitle
                    color: np.idle ? Theme.textDim : Theme.text
                    font.pixelSize: Theme.fontTitle
                    font.weight: Font.DemiBold
                    wrapMode: Text.WordWrap
                    maximumLineCount: 3
                    elide: Text.ElideRight
                }
                Label {
                    Layout.fillWidth: true
                    text: np.shownArtist
                    color: Theme.textDim
                    font.pixelSize: Theme.fontBody
                    wrapMode: Text.WordWrap
                    maximumLineCount: 2
                    elide: Text.ElideRight
                }
            }
        }

        ProgressBar {
            Layout.fillWidth: true
            Layout.topMargin: 14
            value: media.duration > 0 ? media.position / media.duration : 0
        }
        RowLayout {
            Layout.fillWidth: true
            Label { text: np.idle ? "" : np.mmss(media.position); color: Theme.textDim; font.pixelSize: Theme.fontSmall }
            Item { Layout.fillWidth: true }
            Label { text: np.idle ? "" : np.mmss(media.duration); color: Theme.textDim; font.pixelSize: Theme.fontSmall }
        }

        Row {
            Layout.alignment: Qt.AlignHCenter
            spacing: 20
            opacity: np.idle ? 0.4 : 1
            enabled: !np.idle
            IconButton { icon: "previous"; size: 76; anchors.verticalCenter: parent.verticalCenter; onClicked: media.previous() }
            IconButton {
                icon: media.playing ? "pause" : "play"
                primary: true
                size: 96
                onClicked: media.togglePlay()
            }
            IconButton { icon: "next"; size: 76; anchors.verticalCenter: parent.verticalCenter; onClicked: media.next() }
        }
    }
}
