"""Shared constants for the Polymarket agent."""

# Network configuration --------------------------------------------------------

# Default Polygon RPC endpoint used for approval initialization.
POLYGON_RPC_URL = "https://polygon-rpc.com"

# Contracts -------------------------------------------------------------------

# ERC-20 USDC contract on Polygon.
POLYMARKET_USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"

# ERC-1155 Conditional Tokens Framework (CTF) contract on Polygon.
POLYMARKET_CTF_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"

# Exchange and adapter contracts that require approvals for trading.
POLYMARKET_APPROVAL_SPENDERS = (
    "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E",  # CTF Exchange
    "0xC5d563A36AE78145C45a50134d48A1215220f80a",  # Neg Risk Exchange
    "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296",  # Neg Risk Adapter
)

# Maximum allowance used when approving ERC-20 spenders.
MAX_APPROVAL_AMOUNT = (1 << 256) - 1
