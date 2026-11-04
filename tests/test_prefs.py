import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.prefs import as_bool, as_json


class AsBoolTests(unittest.TestCase):
    def test_true_forms(self):
        for v in (True, "true", "True", " TRUE ", "1", "yes", "Yes"):
            self.assertTrue(as_bool(v), v)

    def test_false_forms(self):
        for v in (False, "false", "False", "0", "no", ""):
            self.assertFalse(as_bool(v, True), v)

    def test_default_when_missing_or_odd(self):
        self.assertTrue(as_bool(None, True))
        self.assertFalse(as_bool(None))
        self.assertTrue(as_bool(["true"], True))
        self.assertFalse(as_bool(["true"]))
        self.assertTrue(as_bool("maybe", True))


class AsJsonTests(unittest.TestCase):
    def test_good_list(self):
        self.assertEqual(as_json('[{"a": 1}]', list, []), [{"a": 1}])

    def test_wrong_type_gives_default(self):
        self.assertEqual(as_json("5", list, []), [])
        self.assertEqual(as_json("null", list, []), [])
        self.assertEqual(as_json('{"a": 1}', list, []), [])

    def test_garbage_and_none(self):
        self.assertEqual(as_json("{not json", list, []), [])
        self.assertEqual(as_json(None, list, []), [])
        self.assertEqual(as_json("[" * 100000, list, []), [])


if __name__ == "__main__":
    unittest.main()
