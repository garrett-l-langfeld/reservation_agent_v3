from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class PlatformAdapter(ABC):
    @abstractmethod
    def ensure_authenticated(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def resolve_restaurant(self, restaurant_name: str, location: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get_availability(
        self,
        restaurant_id: str,
        date: str,
        party_size: int,
        time: str | None = None,
        time_range: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def attempt_booking(
        self,
        restaurant_id: str,
        date: str,
        party_size: int,
        slot_time: str,
        user_details: dict[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def generate_handoff(
        self,
        restaurant_id: str,
        date: str,
        party_size: int,
        requested_time: str | None = None,
    ) -> str:
        raise NotImplementedError
