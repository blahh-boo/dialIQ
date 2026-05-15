"""Live Vapi voice provider — fires real outbound calls via Vapi API."""

from __future__ import annotations

from vapi import Vapi
from vapi.types import AssistantOverrides, CreateCustomerDto

from mystery_shop.voice.base import PlacedCall


class VapiProvider:
    """Initiates outbound calls via Vapi. Outcome arrives via POST /vapi/webhook."""

    def __init__(
        self,
        *,
        api_key: str,
        phone_number_id: str,
    ) -> None:
        self._client = Vapi(token=api_key)
        self._phone_number_id = phone_number_id

    def place_call(
        self,
        *,
        to: str,
        assistant_id: str,
        variables: dict[str, str],  # Protocol signature; widened below for Vapi SDK
    ) -> PlacedCall:
        """Dial *to* using Vapi. Returns immediately; report arrives via webhook."""
        call = self._client.calls.create(
            assistant_id=assistant_id,
            phone_number_id=self._phone_number_id,
            customer=CreateCustomerDto(number=to),
            assistant_overrides=AssistantOverrides(variable_values=dict(variables)),
        )
        return PlacedCall(vapi_call_id=call.id or "", report=None)
