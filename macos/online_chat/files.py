"""Private immutable upload copies; never store file bytes in chat JSON."""
import os
from pathlib import Path
import uuid
import tempfile
import subprocess

try:
    from PIL import Image, ImageOps
except ImportError:  # The source version still sends originals without Pillow.
    Image = None
    ImageOps = None

LIMIT = 5 * 1024 * 1024


def _stage_photo(source, target):
    if Image is None:
        return False
    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened)
        image.thumbnail((1920, 1920), Image.Resampling.LANCZOS)
        if image.mode not in ("RGB", "L"):
            background = Image.new("RGB", image.size, "white")
            if "A" in image.getbands():
                background.paste(image, mask=image.getchannel("A"))
            else:
                background.paste(image)
            image = background
        elif image.mode == "L":
            image = image.convert("RGB")
        for quality in (82, 70, 58, 46, 34):
            image.save(target, "JPEG", quality=quality, optimize=True, progressive=True)
            if 0 < target.stat().st_size <= LIMIT:
                return True
    target.unlink(missing_ok=True)
    return False


def _stage_video(source, target):
    for preset in ("Preset960x540", "PresetLowQuality"):
        target.unlink(missing_ok=True)
        result = subprocess.run(
            ["/usr/bin/avconvert", "--source", str(source), "--preset", preset,
             "--output", str(target), "--replace"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180, check=False,
        )
        if result.returncode == 0 and target.is_file() and 0 < target.stat().st_size <= LIMIT:
            return True
    target.unlink(missing_ok=True)
    return False


def stage(source, client_id, root=None, media_kind=None):
    directory = Path(root or Path.home() / "Library/Application Support/OfflineChat/uploads") / str(uuid.UUID(client_id))
    original = Path(source)
    target = directory / original.name
    if target.is_file():
        return str(target)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    optimized = directory / (("Фото-" + str(client_id)[:8] + ".jpg") if media_kind == "photo"
                             else ("Видео-" + str(client_id)[:8] + ".m4v"))
    try:
        if media_kind == "photo" and _stage_photo(original, optimized):
            return str(optimized)
        if media_kind == "video" and _stage_video(original, optimized):
            return str(optimized)
    except Exception:
        optimized.unlink(missing_ok=True)
    with open(source, "rb") as stream:
        data = stream.read(LIMIT + 1)
    if not 0 < len(data) <= LIMIT:
        label = "медиафайл" if media_kind in ("photo", "video") else "файл"
        raise ValueError("Не удалось подготовить %s размером до 5 МБ" % label)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        os.replace(temporary, target)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
    return str(target)


def discard(staged_path):
    path = Path(staged_path)
    try:
        path.unlink(missing_ok=True)
        path.parent.rmdir()
    except OSError:
        pass
