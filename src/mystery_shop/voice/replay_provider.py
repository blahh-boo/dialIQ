"""Replay voice provider — loads saved transcript JSON files from disk, no Vapi calls."""

from __future__ import annotations

import json
from pathlib import Path

from mystery_shop.voice.base import EndOfCallReport, PlacedCall


class ReplayProvider:
    """Cycles through transcript JSON files in *transcripts_dir*.

    Each file must be a JSON object matching the EndOfCallReport schema.
    Real call transcripts go in samples/transcripts/ after the first live run.
    """

    def __init__(self, transcripts_dir: Path) -> None:
        files = sorted(transcripts_dir.glob("*.json"))
        if not files:
            raise ValueError(f"No transcript JSON files found in {transcripts_dir}")
        self._files = files
        self._index = 0

    def place_call(
        self,
        *,
        to: str,
        assistant_id: str,
        variables: dict[str, str],
    ) -> PlacedCall:
        path = self._files[self._index % len(self._files)]
        call_number = self._index
        self._index += 1
        data = json.loads(path.read_text())
        report = EndOfCallReport.model_validate(data)
        # Include the call sequence so every placed call gets a UNIQUE id —
        # call_attempts.vapi_call_id is unique-constrained, and a campaign
        # cycles these fixtures many times. The transcript content still cycles.
        return PlacedCall(vapi_call_id=f"replay-{path.stem}-{call_number}", report=report)
