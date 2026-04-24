import asyncio
import json
import os
import pathlib
import sys
import tempfile
import types
import unittest
from unittest import mock


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import server

REAL_MKDTEMP = tempfile.mkdtemp


class ServerTests(unittest.TestCase):
    def test_play_audio_file_uses_ffplay_for_mp3(self) -> None:
        with mock.patch.object(server.shutil, "which", return_value="/usr/bin/ffplay"), mock.patch.object(
            server.subprocess, "run"
        ) as run_mock:
            server._play_audio_file("/tmp/test.mp3")

        run_mock.assert_called_once_with(
            ["/usr/bin/ffplay", "-nodisp", "-autoexit", "-loglevel", "error", "/tmp/test.mp3"],
            check=True,
        )

    def test_play_audio_file_prefers_simpleaudio_for_wav(self) -> None:
        play_mock = mock.Mock()
        wave_object = mock.Mock(play=mock.Mock(return_value=play_mock))
        fake_simpleaudio = types.SimpleNamespace(
            WaveObject=types.SimpleNamespace(from_wave_file=mock.Mock(return_value=wave_object))
        )

        with mock.patch.dict(sys.modules, {"simpleaudio": fake_simpleaudio}), mock.patch.object(
            server.subprocess, "run"
        ) as run_mock:
            server._play_audio_file("/tmp/test.wav")

        fake_simpleaudio.WaveObject.from_wave_file.assert_called_once_with("/tmp/test.wav")
        play_mock.wait_done.assert_called_once()
        run_mock.assert_not_called()

    def test_speak_generates_mp3_and_passes_it_to_playback(self) -> None:
        saved_paths: list[str] = []

        class FakeCommunicate:
            def __init__(self, text: str, voice: str, rate: str) -> None:
                self.text = text
                self.voice = voice
                self.rate = rate

            async def save(self, path: str) -> None:
                saved_paths.append(path)
                with open(path, "wb") as handle:
                    handle.write(b"audio")

        fake_edge_tts = types.SimpleNamespace(Communicate=FakeCommunicate)

        with tempfile.TemporaryDirectory() as temp_root, mock.patch.dict(
            sys.modules, {"edge_tts": fake_edge_tts}
        ), mock.patch.object(
            server.tempfile,
            "mkdtemp",
            side_effect=lambda prefix: REAL_MKDTEMP(prefix=prefix, dir=temp_root),
        ), mock.patch.object(
            server, "_play_audio_file"
        ) as play_mock:
            result = server.speak("hello world")

        self.assertEqual(result, "spoke")
        self.assertEqual(len(saved_paths), 1)
        self.assertTrue(saved_paths[0].endswith("claude_voice.mp3"))
        play_mock.assert_called_once_with(saved_paths[0])
        self.assertFalse(os.path.exists(os.path.dirname(saved_paths[0])))

    def test_listen_for_speech_returns_transcribed_text(self) -> None:
        payload = json.dumps({"success": True, "text": "hello from mic"}).encode()
        response = mock.MagicMock()
        response.read.return_value = payload
        response.__enter__.return_value = response

        with mock.patch.object(server.urllib.request, "urlopen", return_value=response):
            result = server.listen_for_speech(timeout=12)

        self.assertEqual(result, "hello from mic")

    def test_listen_for_speech_handles_missing_server(self) -> None:
        with mock.patch.object(
            server.urllib.request, "urlopen", side_effect=server.urllib.error.URLError("offline")
        ):
            result = server.listen_for_speech()

        self.assertIn("Voice server not running", result)

    def test_start_voice_mode_reports_ready(self) -> None:
        payload = json.dumps({"success": True, "status": "running"}).encode()
        response = mock.MagicMock()
        response.read.return_value = payload
        response.__enter__.return_value = response

        with mock.patch.object(server.urllib.request, "urlopen", return_value=response):
            result = server.start_voice_mode()

        self.assertIn("READY", result)
