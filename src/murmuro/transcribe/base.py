from __future__ import annotations

from typing import Protocol

import numpy as np


class Transcriber(Protocol):
    """A backend that turns PCM audio into text."""

    def transcribe(
        self,
        pcm: np.ndarray,
        sample_rate: int,
        language: str | None = None,
    ) -> str: ...
