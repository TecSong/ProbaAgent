"""Wallet utilities used for creating keypairs for new users."""

from __future__ import annotations

from dataclasses import dataclass

from eth_account import Account
from web3 import Web3


@dataclass(frozen=True, slots=True)
class WalletKeypair:
    """Represents the credentials for a generated wallet."""

    address: str
    private_key: str


def generate_wallet_keypair() -> WalletKeypair:
    """
    Generate a new Ethereum-compatible wallet keypair.

    Returns:
        WalletKeypair: Newly generated wallet credentials.
    """
    fresh_account = Account.create()
    address = Web3.to_checksum_address(fresh_account.address)
    private_key = fresh_account.key.hex()
    return WalletKeypair(address=address, private_key=private_key)
