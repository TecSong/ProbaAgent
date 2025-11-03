"""Service layer for user management."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from .repository import SupabaseUserRepository, UserRepository, UserRepositoryError
from .wallet import generate_wallet_keypair


class UserServiceError(RuntimeError):
    """Raised when user operations fail."""


@dataclass(frozen=True, slots=True)
class UserRecord:
    """A normalized representation of a stored user."""

    id: Optional[str]
    platform: str
    platform_user_id: str
    wallet_address: str
    wallet_private_key: str
    raw: Dict[str, Any]


@dataclass(frozen=True, slots=True)
class TelegramUserInfo:
    """Telegram identity information used to locate or provision a user."""

    telegram_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None

    @property
    def platform(self) -> str:
        return "telegram"

    @property
    def platform_user_id(self) -> str:
        return str(self.telegram_id)

    def to_payload(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "platform": self.platform,
            "platform_user_id": self.platform_user_id,
            "telegram_id": self.telegram_id,
        }
        if self.username is not None:
            payload["username"] = self.username
        if self.first_name is not None:
            payload["first_name"] = self.first_name
        if self.last_name is not None:
            payload["last_name"] = self.last_name
        return payload


class UserService:
    """High level orchestration for user operations."""

    def __init__(self, repository: UserRepository) -> None:
        self._repository = repository

    @classmethod
    def from_env(
        cls, table: str = "users", platform_field: str = "platform"
    ) -> "UserService":
        try:
            repository = SupabaseUserRepository.from_env(
                table=table, platform_field=platform_field
            )
        except UserRepositoryError as exc:
            raise UserServiceError(str(exc)) from exc
        return cls(repository=repository)

    def ensure_telegram_user(self, info: TelegramUserInfo) -> UserRecord:
        """Create a wallet-backed Telegram user when absent."""
        try:
            existing = self._repository.fetch_user(
                info.platform, info.platform_user_id
            )
        except UserRepositoryError as exc:
            raise UserServiceError(str(exc)) from exc
        if existing is not None:
            return self._normalize(existing)

        wallet = generate_wallet_keypair()
        payload = info.to_payload()
        payload.update(
            {
                "wallet_address": wallet.address,
                "wallet_private_key": wallet.private_key,
            }
        )
        try:
            stored = self._repository.insert_user(payload)
        except UserRepositoryError as exc:
            raise UserServiceError(str(exc)) from exc
        return self._normalize(stored)

    def _normalize(self, data: Dict[str, Any]) -> UserRecord:
        wallet_address = str(data.get("wallet_address", "")).strip()
        wallet_private_key = str(data.get("wallet_private_key", "")).strip()
        if not wallet_address or not wallet_private_key:
            raise UserServiceError(
                "User record is missing wallet credentials in Supabase."
            )
        platform = str(data.get("platform", "")).strip()
        platform_user_id = str(data.get("platform_user_id", "")).strip()
        return UserRecord(
            id=_safe_optional_str(data.get("id")),
            platform=platform,
            platform_user_id=platform_user_id,
            wallet_address=wallet_address,
            wallet_private_key=wallet_private_key,
            raw=data,
        )


def _safe_optional_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    return str(value)
