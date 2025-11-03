"""Helpers for retrieving wallet balances."""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from functools import lru_cache

from web3 import Web3
from web3.contract import Contract

from polymarket_agent.constant import POLYGON_RPC_URL, POLYMARKET_USDC_ADDRESS, USDC_DECIMALS


class WalletBalanceError(RuntimeError):
    """Raised when balance retrieval fails."""


@dataclass(frozen=True, slots=True)
class WalletBalances:
    """Represents the token balances associated with a wallet."""

    usdc_e: Decimal
    pol: Decimal

    def format_usdc(self, precision: int = 4) -> str:
        return _format_decimal(self.usdc_e, precision)

    def format_pol(self, precision: int = 6) -> str:
        return _format_decimal(self.pol, precision)


def get_wallet_balances(address: str) -> WalletBalances:
    """
    Retrieve USDC.e and POL (Polygon native) balances for the given address.

    Args:
        address: Wallet address in hex form.

    Returns:
        WalletBalances: Decimal balances for USDC.e (6 decimals) and POL (18 decimals).
    """
    try:
        checksum_address = Web3.to_checksum_address(address)
    except Exception as exc:  # noqa: BLE001
        raise WalletBalanceError(f"Invalid wallet address: {address}") from exc

    web3 = _get_web3()
    try:
        native_balance_wei = web3.eth.get_balance(checksum_address)
    except Exception as exc:  # noqa: BLE001
        raise WalletBalanceError(f"Failed to fetch POL balance: {exc}") from exc

    try:
        usdc_balance = _usdc_contract(web3).functions.balanceOf(checksum_address).call()
    except Exception as exc:  # noqa: BLE001
        raise WalletBalanceError(f"Failed to fetch USDC.e balance: {exc}") from exc

    pol_decimal = Decimal(native_balance_wei) / Decimal(10**18)
    usdc_decimal = Decimal(usdc_balance) / Decimal(10 ** USDC_DECIMALS)

    return WalletBalances(usdc_e=usdc_decimal, pol=pol_decimal)


@lru_cache(maxsize=1)
def _get_web3() -> Web3:
    rpc_url = os.getenv("POLYGON_RPC_URL", POLYGON_RPC_URL)
    provider = Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 10})
    web3 = Web3(provider)
    if not web3.is_connected():
        raise WalletBalanceError("Polygon RPC connection failed.")
    return web3


@lru_cache(maxsize=1)
def _usdc_contract(web3: Web3) -> Contract:
    address = Web3.to_checksum_address(POLYMARKET_USDC_ADDRESS)
    return web3.eth.contract(address=address, abi=_ERC20_BALANCE_OF_ABI)


def _format_decimal(value: Decimal, precision: int) -> str:
    quantize_target = Decimal("1") / (Decimal("10") ** precision)
    rounded = value.quantize(quantize_target, rounding=ROUND_DOWN)
    normalized = rounded.normalize()
    # Avoid scientific notation for very small numbers.
    if normalized == normalized.to_integral():
        return format(normalized, "f")
    return format(normalized, "f")


_ERC20_BALANCE_OF_ABI = [
    {
        "name": "balanceOf",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "account", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
    }
]
