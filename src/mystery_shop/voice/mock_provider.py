"""Mock voice provider — cycles through canned transcripts from samples/transcripts/.

Identical wire behavior to ReplayProvider; kept as a separate class so RUN_MODE=mock
remains a distinct, documented choice (no network, deterministic ordering for CI).
"""

from __future__ import annotations

from pathlib import Path

from mystery_shop.voice.base import PlacedCall
from mystery_shop.voice.replay_provider import ReplayProvider

_FIXTURES = Path(__file__).resolve().parents[3] / "samples" / "transcripts"


class MockProvider:
    """Returns canned transcripts from the repo's sample fixtures, no network."""

    def __init__(self) -> None:
        self._inner = ReplayProvider(transcripts_dir=_FIXTURES)

    def place_call(
        self,
        *,
        to: str,
        assistant_id: str,
        variables: dict[str, str],
    ) -> PlacedCall:
        placed = self._inner.place_call(to=to, assistant_id=assistant_id, variables=variables)
        return PlacedCall(
            vapi_call_id=placed.vapi_call_id.replace("replay-", "mock-", 1),
            report=placed.report,
        )
