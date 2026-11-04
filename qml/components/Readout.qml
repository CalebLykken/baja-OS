import QtQuick

// Compact numeric readout: a legend on top, a big value with its unit below.
// A placeholder value ("", or any dash a caller passes for "no reading") is
// drawn as one dim em dash with no unit, so it cannot pass for a real value at
// a glance, and it can never be in warning. While a real value is in warning
// the legend turns Ember too, so the readout stays marked after the pulse ends.
Column {
    id: r
    property string label
    property string value
    property string unit
    property bool warning: false
    property real _lastPulse: 0
    readonly property bool placeholder: {
        var v = String(value).trim();
        return v === "" || v === "—" || v === "–" || v === "-" || v === "--";
    }
    readonly property bool _warn: warning && !placeholder

    SequentialAnimation {
        id: pulse
        NumberAnimation { target: num; property: "scale"; to: 1.12; duration: 110; easing.type: Easing.OutQuad }
        NumberAnimation { target: num; property: "scale"; to: 1.0; duration: 140; easing.type: Easing.InOutQuad }
        NumberAnimation { target: num; property: "scale"; to: 1.12; duration: 110; easing.type: Easing.OutQuad }
        NumberAnimation { target: num; property: "scale"; to: 1.0; duration: 160; easing.type: Easing.InOutQuad }
    }

    spacing: 2

    // When a value crosses into its warning state, the numeral eases to Ember
    // and pulses twice, then holds still. The pulse is one-shot on purpose: it
    // fires only on the false-to-true edge and never loops, so a driver's eye is
    // caught once and the Pi is not asked to render a continuous animation.
    // The pulse is also rate-limited to once per 30 s. Thresholds have no
    // hysteresis, so a reading sitting on a limit would otherwise flip warning
    // back and forth and pulse repeatedly. The color still follows warning
    // immediately; only the pulse is held off during the cooldown.
    // Scale leaves the layout size alone, so the unit label does not move.
    onWarningChanged: {
        if (warning && !placeholder) {
            var now = Date.now();
            if (now - _lastPulse > 30000) {
                pulse.restart();
                _lastPulse = now;
            }
        } else {
            pulse.stop();
            num.scale = 1;
        }
    }
    onPlaceholderChanged: if (placeholder) { pulse.stop(); num.scale = 1 }

    Legend {
        objectName: "readoutLegend"
        text: r.label
        color: r._warn ? Theme.warn : Theme.textDim
        Behavior on color { ColorAnimation { duration: 180 } }
    }
    Row {
        spacing: 6
        Label {
            id: num
            objectName: "readoutNumeral"
            numeric: true
            text: r.placeholder ? "—" : r.value
            color: r.placeholder ? Theme.textDim : (r._warn ? Theme.warn : Theme.text)
            font.pixelSize: Theme.fontReadout
            font.weight: Theme.numWeight
            transformOrigin: Item.Left
            Behavior on color { ColorAnimation { duration: 180 } }
        }
        Label {
            objectName: "readoutUnit"
            visible: !r.placeholder && r.unit !== ""
            text: r.unit
            color: Theme.textDim
            font.pixelSize: Theme.fontSmall
            anchors.baseline: num.baseline
        }
    }
}
