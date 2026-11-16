.pragma library

// Letter buckets for the album grid's jump rail. Albums are sorted by artist,
// so the rail works on artist names. "The Beatles" files under B, as it does in
// the sort. Anything that does not start with A-Z lands in "#".
var LABELS = ["#", "A-C", "D-F", "G-I", "J-L", "M-O", "P-R", "S-U", "V-Z"]

function bucketOf(name) {
    var s = String(name === undefined || name === null ? "" : name).trim().toUpperCase()
    if (s.indexOf("THE ") === 0)
        s = s.substring(4).trim()
    var c = s.charCodeAt(0)
    if (!(c >= 65 && c <= 90))
        return "#"
    return LABELS[1 + Math.min(7, Math.floor((c - 65) / 3))]   // V to Z share the last bucket
}

// The nine buckets in order, each with the index of its first entry or -1.
function buckets(names) {
    var first = {}
    for (var i = 0; i < names.length; i++) {
        var b = bucketOf(names[i])
        if (first[b] === undefined)
            first[b] = i
    }
    var out = []
    for (var j = 0; j < LABELS.length; j++)
        out.push({ label: LABELS[j], index: first[LABELS[j]] === undefined ? -1 : first[LABELS[j]] })
    return out
}
