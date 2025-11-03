"""Repository layer for persisting user records."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol

from supabase import Client, create_client


class UserRepositoryError(RuntimeError):
    """Raised when the repository cannot complete an operation."""


class UserRepository(Protocol):
    """Protocol describing operations required by the user service."""

    def fetch_user(
        self, platform: str, platform_user_id: str
    ) -> Optional[Dict[str, Any]]:
        """Return a stored user record or ``None`` when absent."""

    def insert_user(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Persist a new user record and return the stored payload."""


@dataclass(slots=True)
class SupabaseConfig:
    url: str
    key: str


class SupabaseUserRepository:
    """Supabase-backed user repository."""

    def __init__(
        self, client: Client, table: str = "users", platform_field: str = "platform"
    ) -> None:
        self._client = client
        self._table = table
        self._platform_field = platform_field

    @classmethod
    def from_env(
        cls, table: str = "users", platform_field: str = "platform"
    ) -> "SupabaseUserRepository":
        config = load_supabase_config()
        client = create_client(config.url, config.key)
        return cls(client=client, table=table, platform_field=platform_field)

    def fetch_user(
        self, platform: str, platform_user_id: str
    ) -> Optional[Dict[str, Any]]:
        try:
            response = (
                self._client.table(self._table)
                .select("*")
                .eq(self._platform_field, platform)
                .eq("platform_user_id", platform_user_id)
                .limit(1)
                .execute()
            )
        except Exception as exc:  # noqa: BLE001
            raise UserRepositoryError(f"Failed to query Supabase: {exc}") from exc

        data = getattr(response, "data", None) or []
        if not data:
            return None
        return data[0]

    def insert_user(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            response = self._client.table(self._table).insert(payload).execute()
        except Exception as exc:  # noqa: BLE001
            # Handle race conditions where another insert happens between fetch and insert.
            if "duplicate key value violates unique constraint" in str(exc).lower():
                platform = payload.get(self._platform_field)
                platform_user_id = str(payload.get("platform_user_id", ""))
                existing = self.fetch_user(platform, platform_user_id)
                if existing is not None:
                    return existing
            raise UserRepositoryError(f"Failed to insert Supabase record: {exc}") from exc

        data = getattr(response, "data", None) or []
        if data:
            return data[0]

        # Some Supabase configurations (e.g. when returning=representation is disabled)
        # do not echo inserted rows. Perform a best-effort fetch in that case.
        platform = str(payload.get(self._platform_field))
        platform_user_id = str(payload.get("platform_user_id", ""))
        existing = self.fetch_user(platform, platform_user_id)
        if existing is None:
            raise UserRepositoryError("Supabase insert succeeded but no data returned.")
        return existing


def load_supabase_config() -> SupabaseConfig:
    """Load Supabase configuration from the environment."""
    url = os.getenv("SUPABASE_URL")
    key = (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or os.getenv("SUPABASE_SERVICE_API_KEY")
        or os.getenv("SUPABASE_ANON_KEY")
    )
    if not url:
        raise UserRepositoryError("Missing SUPABASE_URL environment variable.")
    if not key:
        raise UserRepositoryError(
            "Missing Supabase key. Set SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY."
        )
    return SupabaseConfig(url=url, key=key)
