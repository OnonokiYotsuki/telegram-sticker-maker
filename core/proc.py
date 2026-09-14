"""Hidden-window subprocess helpers and FFmpeg discovery."""
from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any, Sequence

CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def ffmpeg_bin() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise FileNotFoundError("FFmpeg executable not found in system PATH.")
    return path


def ffprobe_bin() -> str | None:
    return shutil.which("ffprobe")


def run_hidden(cmd: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess:
    kwargs.setdefault("stdout", subprocess.PIPE)
    kwargs.setdefault("stderr", subprocess.PIPE)
    kwargs["creationflags"] = kwargs.pop("creationflags", 0) | CREATE_NO_WINDOW
    return subprocess.run(cmd, **kwargs)


def popen_hidden(cmd: Sequence[str], **kwargs: Any) -> subprocess.Popen:
    kwargs["creationflags"] = kwargs.pop("creationflags", 0) | CREATE_NO_WINDOW
    return subprocess.Popen(cmd, **kwargs)
