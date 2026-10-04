"""Join paused recordings outside the UI thread, without video re-encoding."""
import os
import subprocess
import tempfile
import uuid


def join_segments(executable, paths, video):
    if not paths:
        raise ValueError("Нет записанных фрагментов")
    if len(paths) == 1:
        return paths[0]
    output = os.path.join(tempfile.gettempdir(), f"oc-{'circle' if video else 'voice'}-{uuid.uuid4()}.{'mp4' if video else 'm4a'}")
    # Explicit file: protocol: a manifest read from pipe:0 otherwise resolves
    # absolute names relative to the pipe protocol on recent FFmpeg versions.
    manifest = "".join("file 'file:" + os.path.abspath(path).replace("'", "'\\''") + "'\n" for path in paths)
    try:
        result = subprocess.run([executable, "-v", "error", "-y", "-protocol_whitelist", "file,pipe",
                                 "-f", "concat", "-safe", "0", "-i", "pipe:0", "-c", "copy",
                                 "-movflags", "+faststart", output], input=manifest.encode(),
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as error:
        if os.path.isfile(output): os.unlink(output)
        raise RuntimeError("Не удалось соединить фрагменты записи") from error
    if result.returncode or not os.path.isfile(output) or os.path.getsize(output) < 1000:
        if os.path.isfile(output): os.unlink(output)
        raise RuntimeError("Не удалось соединить фрагменты записи")
    return output
