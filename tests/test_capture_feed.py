import io
import os
import shutil
import subprocess
import tempfile
import unittest
from desktop_chat.capture_preview import CaptureFeed, capture_arguments, SIDE


class CaptureFeedTests(unittest.TestCase):
    def test_audio_level_comes_from_microphone_metadata(self):
        feed = CaptureFeed.__new__(CaptureFeed)
        feed.closed, feed.ready, feed.level = False, False, 0
        feed.read_levels(io.BytesIO(b"lavfi.astats.Overall.RMS_level=-30\n"))
        self.assertTrue(feed.ready)
        self.assertEqual(feed.level, 0.5)

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is not installed")
    def test_file_and_live_frames_use_one_capture_input(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "circle.mp4")
            args = capture_arguments(shutil.which("ffmpeg"), path, True)
            self.assertEqual(args.count("-i"), 1)
            # Synthetic sources only: never open the user's camera or microphone.
            suffix = args[args.index("-t"):]
            suffix = ["0.6" if value == "60" else value for value in suffix]
            command = [args[0], "-y", "-nostats", "-f", "lavfi", "-i",
                       "testsrc=size=320x240:rate=30", "-f", "lavfi", "-i",
                       "sine=frequency=440:sample_rate=44100"] + suffix
            result = subprocess.run(command, capture_output=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
            self.assertGreater(os.path.getsize(path), 1000)
            self.assertGreaterEqual(len(result.stdout), SIDE * SIDE * 3)
            self.assertEqual(len(result.stdout) % (SIDE * SIDE * 3), 0)
            self.assertIn(b"lavfi.astats.Overall.RMS_level=", result.stderr)
