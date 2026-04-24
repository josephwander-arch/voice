import importlib.util
import pathlib
import sys
import types
import unittest
from unittest import mock


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
VOICE_SERVER_PATH = REPO_ROOT / "voice_server.py"


def load_voice_server_module():
    spec = importlib.util.spec_from_file_location("voice_server_under_test", VOICE_SERVER_PATH)
    module = importlib.util.module_from_spec(spec)

    fake_pyaudio = types.SimpleNamespace(paInt16=16, PyAudio=object)

    class FakeWhisperModel:
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

        def transcribe(self, *args, **kwargs):
            return [], {}

    fake_faster_whisper = types.SimpleNamespace(WhisperModel=FakeWhisperModel)

    with mock.patch.dict(
        sys.modules,
        {
            "pyaudio": fake_pyaudio,
            "faster_whisper": fake_faster_whisper,
        },
    ):
        assert spec.loader is not None
        spec.loader.exec_module(module)
    return module


class VoiceServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.voice_server = load_voice_server_module()

    def test_default_listen_config_enables_noise_filter(self) -> None:
        with mock.patch.object(self.voice_server, "VOICE_CONFIG_PATH", None):
            defaults = self.voice_server.get_listen_defaults()

        self.assertEqual(defaults["silence_timeout"], self.voice_server.DEFAULT_SILENCE_TIMEOUT)
        self.assertTrue(defaults["noise_filter_enabled"])
        self.assertTrue(defaults["emotion_enabled"])

    def test_env_flag_can_disable_emotion_globally(self) -> None:
        with mock.patch.dict(self.voice_server.os.environ, {"VOICE_EMOTION_ENABLED": "false"}, clear=False), mock.patch.object(
            self.voice_server, "VOICE_CONFIG_PATH", None
        ):
            defaults = self.voice_server.get_listen_defaults()

        self.assertFalse(defaults["emotion_enabled"])

    def test_listen_endpoint_enables_emotion_by_default(self) -> None:
        dummy = types.SimpleNamespace(path="/listen?timeout=9")
        capture_args = {}

        def capture_voice(timeout, skip_emotion, skip_filter, silence_timeout, min_speech_duration, rms_threshold):
            capture_args.update(
                timeout=timeout,
                skip_emotion=skip_emotion,
                skip_filter=skip_filter,
                silence_timeout=silence_timeout,
                min_speech_duration=min_speech_duration,
                rms_threshold=rms_threshold,
            )
            return {"success": True}

        dummy.capture_voice = capture_voice
        dummy.send_json = lambda payload: capture_args.update(payload=payload)

        with mock.patch.object(
            self.voice_server,
            "get_listen_defaults",
            return_value={
                "silence_timeout": 4.0,
                "min_speech_duration": 3.0,
                "rms_threshold": 100,
                "pre_record_enabled": True,
                "noise_filter_enabled": True,
                "emotion_enabled": True,
            },
        ):
            self.voice_server.VoiceHandler.do_POST(dummy)

        self.assertEqual(capture_args["timeout"], 9)
        self.assertFalse(capture_args["skip_emotion"])
        self.assertFalse(capture_args["skip_filter"])
        self.assertEqual(capture_args["payload"], {"success": True})

    def test_listen_endpoint_honors_skip_emotion_query_param(self) -> None:
        dummy = types.SimpleNamespace(path="/listen?skip_emotion=true&skip_filter=true")
        capture_args = {}

        def capture_voice(timeout, skip_emotion, skip_filter, silence_timeout, min_speech_duration, rms_threshold):
            capture_args.update(
                timeout=timeout,
                skip_emotion=skip_emotion,
                skip_filter=skip_filter,
            )
            return {"success": True}

        dummy.capture_voice = capture_voice
        dummy.send_json = lambda payload: None

        with mock.patch.object(
            self.voice_server,
            "get_listen_defaults",
            return_value={
                "silence_timeout": 4.0,
                "min_speech_duration": 3.0,
                "rms_threshold": 100,
                "pre_record_enabled": True,
                "noise_filter_enabled": True,
                "emotion_enabled": True,
            },
        ):
            self.voice_server.VoiceHandler.do_POST(dummy)

        self.assertEqual(capture_args["timeout"], 60)
        self.assertTrue(capture_args["skip_emotion"])
        self.assertTrue(capture_args["skip_filter"])

    def test_listen_endpoint_respects_global_emotion_disable(self) -> None:
        dummy = types.SimpleNamespace(path="/listen")
        capture_args = {}

        def capture_voice(timeout, skip_emotion, skip_filter, silence_timeout, min_speech_duration, rms_threshold):
            capture_args.update(timeout=timeout, skip_emotion=skip_emotion, skip_filter=skip_filter)
            return {"success": True}

        dummy.capture_voice = capture_voice
        dummy.send_json = lambda payload: None

        with mock.patch.object(
            self.voice_server,
            "get_listen_defaults",
            return_value={
                "silence_timeout": 4.0,
                "min_speech_duration": 3.0,
                "rms_threshold": 100,
                "pre_record_enabled": True,
                "noise_filter_enabled": True,
                "emotion_enabled": False,
            },
        ):
            self.voice_server.VoiceHandler.do_POST(dummy)

        self.assertEqual(capture_args["timeout"], 60)
        self.assertTrue(capture_args["skip_emotion"])
        self.assertFalse(capture_args["skip_filter"])

    def test_log_message_formats_output(self) -> None:
        dummy = types.SimpleNamespace()

        with mock.patch("builtins.print") as print_mock:
            self.voice_server.VoiceHandler.log_message(dummy, "%s %s", "voice", "ready")

        print_mock.assert_called_once_with("[Voice] voice ready")
