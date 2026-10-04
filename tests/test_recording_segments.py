"""Synthetic media only. Never opens a real camera/microphone."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from desktop_chat.recording_segments import join_segments


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is not installed")
class RecordingSegmentTests(unittest.TestCase):
    def test_pause_removes_gap_from_voice_and_video(self):
        ffmpeg = shutil.which("ffmpeg")
        ffprobe = shutil.which("ffprobe")
        with tempfile.TemporaryDirectory(prefix="recording ' test ") as folder:
            for video in (False, True):
                paths = []
                for number in range(2):
                    path = os.path.join(folder, f"part {number}.{'mp4' if video else 'm4a'}")
                    args = [ffmpeg, "-v", "error", "-y"]
                    if video: args += ["-f", "lavfi", "-i", "testsrc=size=160x160:rate=30"]
                    args += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=24000", "-t", "0.7"]
                    if video: args += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
                    args += ["-c:a", "aac", path]
                    subprocess.run(args, check=True, capture_output=True, timeout=15)
                    paths.append(path)
                merged = join_segments(ffmpeg, paths, video)
                try:
                    result = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "json", merged], capture_output=True, check=True, timeout=5)
                    duration = float(json.loads(result.stdout)["format"]["duration"])
                    self.assertGreater(duration, 1.2)
                    self.assertLess(duration, 1.7)
                    # Inputs are retained until the owner confirms successful output.
                    self.assertTrue(all(os.path.isfile(path) for path in paths))
                finally: os.unlink(merged)

    def test_single_segment_needs_no_extra_process(self):
        self.assertEqual(join_segments("not-used", ["voice.m4a"], False), "voice.m4a")

    def test_empty_recording_is_not_sendable(self):
        with self.assertRaises(ValueError): join_segments("not-used", [], False)
