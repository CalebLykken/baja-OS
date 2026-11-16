"""The A-Z jump rail's bucketing (qml/components/AlphaIndex.js)."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QCoreApplication
from PyQt6.QtQml import QJSEngine

PATH = os.path.join(os.path.dirname(__file__), "..", "qml", "components", "AlphaIndex.js")


class AlphaIndexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])
        cls.engine = QJSEngine()
        src = open(PATH).read().replace(".pragma library", "")
        cls.engine.evaluate(src)

    def buckets(self, names):
        arg = "[" + ",".join(repr(n) for n in names) + "]"
        r = self.engine.evaluate("JSON.stringify(buckets(%s))" % arg)
        import json
        return {b["label"]: b["index"] for b in json.loads(r.toString())}

    def bucket(self, name):
        return self.engine.evaluate("bucketOf(%r)" % name).toString()

    def test_sorted_artists(self):
        b = self.buckets(["ABBA", "The Beatles", "Cher", "Dr Dre", "Zed"])
        self.assertEqual(b["A-C"], 0)
        self.assertEqual(b["D-F"], 3)
        self.assertEqual(b["V-Z"], 4)
        for empty in ("#", "G-I", "J-L", "M-O", "P-R", "S-U"):
            self.assertEqual(b[empty], -1)

    def test_nine_ordered_buckets(self):
        r = self.engine.evaluate("buckets([]).map(function (b) { return b.label }).join()")
        self.assertEqual(r.toString(), "#,A-C,D-F,G-I,J-L,M-O,P-R,S-U,V-Z")

    def test_digits_and_other(self):
        self.assertEqual(self.bucket("50 Cent"), "#")
        self.assertEqual(self.bucket("!!!"), "#")
        self.assertEqual(self.bucket(""), "#")
        self.assertEqual(self.buckets(["10cc", "Abba"])["#"], 0)

    def test_the_prefix_dropped(self):
        self.assertEqual(self.bucket("The Who"), "V-Z")
        self.assertEqual(self.bucket("the clash"), "A-C")
        self.assertEqual(self.bucket("Theory"), "S-U")

    def test_letter_edges(self):
        self.assertEqual(self.bucket("Cc"), "A-C")
        self.assertEqual(self.bucket("Dd"), "D-F")
        self.assertEqual(self.bucket("Ss"), "S-U")
        self.assertEqual(self.bucket("Vv"), "V-Z")
        self.assertEqual(self.bucket("Zz"), "V-Z")


if __name__ == "__main__":
    unittest.main()
