"""Offline checks for the single-capture listen integration."""
import io
import json
import os
import subprocess
import tempfile
import unittest
import wave
from unittest import mock

import numpy as np
from nowhere import listen


class HearingTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_pcm_used_for_acoustics_and_hearing(self):
        pcm = (np.sin(np.arange(22050) * 0.15) * 9000).astype("<i2").tobytes()
        proc = subprocess.CompletedProcess([], 0, pcm, b"")
        with mock.patch.object(listen.shutil, "which", return_value="ffmpeg"), mock.patch.object(listen, "_run_subprocess", new=mock.AsyncMock(return_value=proc)) as capture, mock.patch.object(listen, "_hear_wav", new=mock.AsyncMock(return_value={"analyzed": True, "transcript": "ciao"})) as hear:
            result = await listen.capture("https://radio.example/stream", 5)
        capture.assert_awaited_once()
        hear.assert_awaited_once()
        with wave.open(io.BytesIO(hear.call_args.args[0]), "rb") as wav:
            self.assertEqual(wav.getframerate(), 22050)
            self.assertEqual(wav.readframes(wav.getnframes()), pcm)
        self.assertTrue(result["analyzed"])
        self.assertEqual(result["hearing"]["transcript"], "ciao")

    async def test_forbidden_does_not_call_hearing_or_download_again(self):
        proc = subprocess.CompletedProcess([], 1, b"", b"Server returned 403 Forbidden")
        with mock.patch.object(listen.shutil, "which", return_value="ffmpeg"), mock.patch.object(listen, "_run_subprocess", new=mock.AsyncMock(return_value=proc)), mock.patch.object(listen, "_hear_wav", new=mock.AsyncMock()) as hear, mock.patch.object(listen, "_capture_degraded", new=mock.AsyncMock()) as retry:
            result = await listen.capture("https://radio.example/stream", 5)
        hear.assert_not_called()
        retry.assert_not_called()
        self.assertFalse(result["analyzed"])
        self.assertEqual(result["hearing"]["error"], "stream_forbidden")
        self.assertEqual(result["hearing"]["http_status"], 403)

    async def test_optional_provider_and_failure(self):
        with mock.patch.dict(os.environ, {"NOWHERE_HEARING_COMMAND": ""}):
            self.assertEqual((await listen._hear_wav(b"wav"))["error"], "hearing_not_configured")
        with mock.patch.dict(os.environ, {"NOWHERE_HEARING_COMMAND": '["python", "ear.py", "--analyze-wav"]'}), mock.patch.object(listen.subprocess, "run", side_effect=subprocess.TimeoutExpired("ear", 95)):
            self.assertEqual((await listen._hear_wav(b"wav"))["error"], "hearing_timeout")

    async def test_provider_gets_audio_on_stdin_not_url_and_audio_is_not_returned(self):
        proc = subprocess.CompletedProcess([], 0, json.dumps({"analyzed": True, "transcript": "ciao", "audio": "secret"}).encode(), b"")
        with mock.patch.dict(os.environ, {"NOWHERE_HEARING_COMMAND": '["python", "ear.py", "--analyze-wav"]'}), mock.patch.object(listen.subprocess, "run", return_value=proc) as run:
            result = await listen._hear_wav(b"existing-wav")
        self.assertEqual(run.call_args.kwargs["input"], b"existing-wav")
        self.assertNotIn("audio", result)

    async def test_listen_retains_url_and_genre_fallback_on_capture_failure(self):
        # Import and run against isolated state; never save an actual journey.
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, {"NOWHERE_HOME": directory}):
            from nowhere import server
        state = mock.Mock(pos=(41.9, 12.5), last_env={}, biome="city", mode="walk")
        station = {"name": "Rai Radio 1", "genre": "news/talk", "stream_url": "https://radio.example/1.mp3"}
        hearing = {"analyzed": False, "error": "stream_forbidden", "stage": "capture"}
        analysis = {**listen._degraded_result(), "hearing": hearing}
        with mock.patch.object(server, "_state", state), mock.patch.object(server, "_get_radio", new=mock.AsyncMock(return_value=station)), mock.patch.object(server.listen_mod, "capture", new=mock.AsyncMock(return_value=analysis)), mock.patch.object(server, "_try_play_stream", new=mock.AsyncMock(return_value=False)), mock.patch.object(server, "_last_env_surface", return_value={}), mock.patch.object(server, "_record_footprint") as record, mock.patch.object(server.soundscape, "describe_sound", return_value="风起来了。"), mock.patch.object(server.soundscape, "soundscape_credit", return_value=""):
            result = await server.listen_impl(5)
        self.assertEqual(result["data"]["stream_url"], station["stream_url"])
        self.assertEqual(result["data"]["hearing"], hearing)
        self.assertFalse(result["data"]["heard"])
        self.assertEqual(result["data"]["radio_description_source"], "genre_fallback")
        self.assertIn("有人在说话，语速不快不慢。", result["text"])
        self.assertNotIn("hearing", record.call_args.kwargs)
        state.save.assert_called_once()


if __name__ == "__main__":
    unittest.main()
