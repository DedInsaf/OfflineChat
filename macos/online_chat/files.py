"""Private immutable upload copies; never store file bytes in chat JSON."""
import os
from pathlib import Path
import uuid
import tempfile

LIMIT = 5 * 1024 * 1024


def stage(source, client_id, root=None):
    directory = Path(root or Path.home() / "Library/Application Support/OfflineChat/uploads") / str(uuid.UUID(client_id))
    target = directory / Path(source).name
    if target.is_file():
        return str(target)
    with open(source, "rb") as stream:
        data = stream.read(LIMIT + 1)
    if not 0 < len(data) <= LIMIT:
        raise ValueError("Выберите непустой файл размером до 5 МБ")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
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
