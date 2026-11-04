import QtQuick

// Text in the active style's font. Use this instead of Text so a style
// change reaches every label.
Text {
    property bool numeric: false   // big numbers use the style's number font

    // Names reach the UI from outside (Wi-Fi SSIDs, track titles, tags, place
    // names sent from a phone), so never interpret them as markup. A label
    // that really wants StyledText/RichText can set textFormat itself.
    textFormat: Text.PlainText

    color: Theme.text
    font.family: numeric ? Theme.numFont : Theme.font
    font.italic: numeric && Theme.numItalic
}
