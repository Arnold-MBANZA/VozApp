import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from transcriber.engine import Segment, TranscriptionResult
from transcriber.formatters import build_exports, srt_text, timestamp


class FormatterTests(unittest.TestCase):
    def test_timestamp_formats(self) -> None:
        self.assertEqual(timestamp(65.25), "00:01:05:250")
        self.assertEqual(timestamp(65.25, srt=True), "00:01:05,250")

    def test_exports(self) -> None:
        result = TranscriptionResult(
            text="Olá mundo.", segments=[Segment(0.0, 2.5, "Olá mundo.")], duration_seconds=2.5
        )
        with tempfile.TemporaryDirectory() as directory:
            exports = build_exports(result, "aula teste", Path(directory), ["txt", "md", "srt", "docx"])
            self.assertEqual(exports["txt"].read_text(encoding="utf-8"), "Olá mundo.\n")
            self.assertIn("[00:00:00]", exports["md"].read_text(encoding="utf-8"))
            self.assertIn("00:00:00,000 --> 00:00:02,500", srt_text(result.segments))
            with ZipFile(exports["docx"]) as document:
                word_xml = document.read("word/document.xml").decode("utf-8")
            self.assertIn("Olá mundo.", word_xml)
            self.assertIn("[00:00:00]", word_xml)


if __name__ == "__main__":
    unittest.main()
