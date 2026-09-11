from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests._stubs import install_dependency_stubs

install_dependency_stubs()

from fastapi import HTTPException

from src.api import music as music_api
from src.settings import settings


class MusicApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmpdir.name)
        self.patcher = mock.patch.object(settings, "music_asset_dir", str(self.tmp_path))
        self.patcher.start()

    def tearDown(self) -> None:
        self.patcher.stop()
        self.tmpdir.cleanup()

    def test_track_list_reports_asset_availability(self) -> None:
        listing = music_api.list_music_tracks()
        self.assertFalse(listing["tracks"][0]["available"])

        (self.tmp_path / music_api.TRACK_FILENAME).write_bytes(b"framed-opus")
        listing = music_api.list_music_tracks()
        self.assertTrue(listing["tracks"][0]["available"])
        self.assertEqual(listing["tracks"][0]["id"], "try-everything")

    def test_stream_returns_framed_opus_headers_and_bytes(self) -> None:
        expected = b"framed-opus-packets"
        (self.tmp_path / music_api.TRACK_FILENAME).write_bytes(expected)

        response = music_api.stream_music_track()

        self.assertEqual(response.media_type, "application/octet-stream")
        self.assertEqual(response.headers["X-Audio-Format"], "opus")
        self.assertEqual(response.headers["X-Audio-Packetization"], "framed-v1")
        self.assertEqual(response.headers["X-Opus-Sample-Rate"], "16000")
        self.assertEqual(b"".join(response.body_iterator), expected)

    def test_stream_returns_404_until_asset_is_deployed(self) -> None:
        with self.assertRaises(HTTPException) as context:
            music_api.stream_music_track()
        self.assertEqual(context.exception.status_code, 404)
        self.assertEqual(context.exception.detail, "music_track_not_ready")


if __name__ == "__main__":
    unittest.main()
