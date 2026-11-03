"""The shared Label shows names that come from outside (Wi-Fi SSIDs, track
titles, tags, phone-sent place names), so it must render plain text and never
interpret them as markup.

    python3 -m unittest tests.test_label_plaintext
"""

import re
import unittest
from pathlib import Path

QML = Path(__file__).resolve().parent.parent / "qml"


class LabelPlainTextTests(unittest.TestCase):
    def test_label_defaults_to_plain_text(self):
        src = (QML / "components" / "Label.qml").read_text()
        self.assertRegex(src, r"(?m)^\s*textFormat:\s*Text\.PlainText\b")

    def test_no_label_relies_on_markup(self):
        # Nothing in the app's own strings may need styled text, or switching
        # the default would change what's shown.
        pat = re.compile(r"text:\s*[^\n]*</?(b|i|br|font|span|u)\b|&(amp|lt|gt|nbsp);")
        for path in QML.rglob("*.qml"):
            self.assertIsNone(pat.search(path.read_text()), str(path))


if __name__ == "__main__":
    unittest.main()
