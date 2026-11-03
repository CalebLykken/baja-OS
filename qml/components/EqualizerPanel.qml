import QtQuick
import QtQuick.Layouts

// The equalizer: presets on top, then the five bands as segmented columns
// with their setting above and their name below. Used on the Music page and
// in Settings > Sound.
ColumnLayout {
    id: panel
    spacing: 16

    function signed(v) { return v > 0 ? "+" + v : String(v) }

    RowLayout {
        Layout.fillWidth: true
        spacing: 16
        SegmentedControl {
            options: eq.presetNames.map(n => ({ label: n, value: n }))
            current: eq.preset
            onPicked: (v) => eq.applyPreset(v)
        }
        Label {
            visible: eq.preset === "Custom"
            text: "Your own"
            color: Theme.textDim
            font.pixelSize: Theme.fontBody
        }
        Item { Layout.fillWidth: true }
    }

    RowLayout {
        Layout.fillWidth: true
        Layout.fillHeight: true
        spacing: 8

        Repeater {
            model: eq.bands
            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.preferredWidth: 1        // equal columns
                spacing: 8
                Label {
                    Layout.alignment: Qt.AlignHCenter
                    text: panel.signed(eq.gains[index]) + " dB"
                    color: eq.gains[index] === 0 ? Theme.textDim : Theme.text
                    font.family: Theme.numFont
                    font.pixelSize: Theme.fontBody
                    font.weight: Font.DemiBold
                }
                // Fills the column's width (its touch area); the segments
                // stay a fixed width in the middle. A new preset glides the
                // columns over (staggered by band); the dB labels above
                // still jump to the true setting at once.
                EqSlider {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.minimumHeight: 120
                    value: eq.gains[index]
                    delay: index * 35       // preset change ripples low to high
                    limit: eq.limit
                    onMoved: (v) => eq.setGain(index, v)
                }
                Legend {
                    Layout.alignment: Qt.AlignHCenter
                    text: modelData.label
                    font.letterSpacing: 1
                }
                Label {
                    Layout.alignment: Qt.AlignHCenter
                    text: modelData.freqText + " Hz"
                    color: Theme.textDim
                    font.pixelSize: Theme.fontSmall
                }
            }
        }
    }

    Label {
        visible: !eq.available
        Layout.fillWidth: true
        wrapMode: Text.WordWrap
        color: Theme.textDim
        font.pixelSize: Theme.fontSmall
        text: !eq.supported ? "The equalizer works on the Pi; here it only remembers your settings."
              : "The equalizer isn't running. Run deploy/audio/install-eq.sh on the Pi."
    }
}
