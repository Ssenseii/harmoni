import json
import os
import shutil
import uuid
from typing import Any, Optional

from utils.logger import log_warning


def write_json_atomic(path: str, data: Any, *, indent: int = 2, mode: Optional[int] = None) -> None:
    """Write data as UTF-8 JSON to path through a temp file and an atomic replace.

    @param path: Destination file, parent directories are created when missing.
    @param data: JSON-serialisable value to write.
    @param indent: Indent passed to json.dump.
    @param mode: Optional permission bits (for example 0o600) for the final file on POSIX.
    """
    path = os.path.abspath(path)
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)

    tmp_path = os.path.join(directory, f".{os.path.basename(path)}.{uuid.uuid4().hex}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    if mode is None and os.name != "nt" and os.path.exists(path):
        mode = os.stat(path).st_mode & 0o777
    fd = os.open(tmp_path, flags, 0o666 if mode is None else mode)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            if mode is not None and hasattr(os, "fchmod"):
                os.fchmod(f.fileno(), mode)
            json.dump(data, f, indent=indent)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def _corrupt_target(path: str) -> str:
    """Return a free "<path>.corrupt" name, adding a numeric suffix when taken.

    @param path: Path of the corrupt file.
    """
    candidate = f"{path}.corrupt"
    counter = 1
    while os.path.exists(candidate):
        candidate = f"{path}.corrupt.{counter}"
        counter += 1
    return candidate


def load_json(path: str, default: Any) -> Any:
    """Read JSON from path, returning default when missing or empty, and moving a corrupt file to "<path>.corrupt".

    @param path: File to read.
    @param default: Value returned when the file cannot provide data.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        return default
    except UnicodeDecodeError as e:
        _quarantine(path, e)
        return default
    except OSError as e:
        log_warning(f"Could not read {path}: {e}")
        return default

    if not text.strip():
        return default

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        _quarantine(path, e)
        return default


def _quarantine(path: str, error: Exception) -> None:
    """Move a corrupt JSON file aside and log where it went.

    @param path: Path of the corrupt file.
    @param error: The decode error that was raised.
    """
    target = _corrupt_target(path)
    try:
        os.rename(path, target)
    except OSError:
        try:
            shutil.copy2(path, target)
        except OSError as copy_error:
            log_warning(f"{path} is corrupt ({error}) and could not be preserved: {copy_error}")
            return
    log_warning(f"{path} is corrupt ({error}). Kept a copy at {target} and using defaults.")
