"""Titles made from file names when a song has no title tag."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.ffmpeg*=false")

try:
    from mutagen.id3 import TIT2
    from mutagen.wave import WAVE
    from backend import library
    from backend.library import scan, tidy_title
    from tests.test_library import write_wav
except ImportError as e:
    raise unittest.SkipTest(f"PyQt6 or mutagen isn't installed ({e})")


class TidyTitleTest(unittest.TestCase):
    def test_track_number_and_underscores_go(self):
        self.assertEqual(tidy_title("01 - Gravel_Road"), "Gravel Road")
        self.assertEqual(tidy_title("1. Gravel Road"), "Gravel Road")
        self.assertEqual(tidy_title("07 Gravel Road"), "Gravel Road")

    def test_a_freesound_name_is_readable(self):
        name = tidy_title("575780__humanoide9000__epic-trailer-action-music")
        self.assertEqual(name, "humanoide9000 epic-trailer-action-music")
        self.assertNotIn("__", name)
        self.assertNotIn("  ", name)

    def test_repeated_spaces_and_dashes_collapse(self):
        self.assertEqual(tidy_title("a___b   c"), "a b c")
        self.assertEqual(tidy_title("a---b"), "a-b")

    def test_a_dashed_track_number_without_spaces_goes(self):
        self.assertEqual(tidy_title("01-Intro"), "Intro")

    def test_a_year_or_number_title_with_a_space_stays(self):
        self.assertEqual(tidy_title("1979 Smashing Pumpkins"), "1979 Smashing Pumpkins")
        self.assertEqual(tidy_title("2112 Overture"), "2112 Overture")

    def test_an_all_digit_title_stays(self):
        self.assertEqual(tidy_title("2112"), "2112")

    def test_a_name_that_empties_out_stays_as_it_was(self):
        self.assertEqual(tidy_title("01 - "), "01 - ")
        self.assertEqual(tidy_title("___"), "___")
        self.assertEqual(tidy_title("1."), "1.")


class ScanTitleTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        env = mock.patch.dict(os.environ, {"XDG_CACHE_HOME": str(self.root / "cache")})
        env.start()
        self.addCleanup(env.stop)

    def test_stem_titles_are_tidied_and_tagged_ones_are_not(self):
        top = self.root / "songs"
        top.mkdir()
        write_wav(top / "01 - Gravel_Road.wav", 0.001)
        tagged = top / "02_Raw_Name.wav"
        write_wav(tagged, 0.001)
        audio = WAVE(str(tagged))
        audio.add_tags()
        audio.tags.add(TIT2(encoding=3, text=["My_Title - 01"]))
        audio.save()
        titles = {Path(t["path"]).name: t["title"] for t in scan(top)}
        self.assertEqual(titles["01 - Gravel_Road.wav"], "Gravel Road")
        self.assertEqual(titles["02_Raw_Name.wav"], "My_Title - 01")

    def test_an_old_cache_is_read_again(self):
        self.assertEqual(library.CACHE_VERSION, 2)


if __name__ == "__main__":
    unittest.main()
