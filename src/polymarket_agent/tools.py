from __future__ import annotations

from typing import Callable, List

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, confloat, conint

from .client import PolymarketClient


class ListOrdersInput(BaseModel):
    market_id: str | None = Field(
        default=None,
        description="Optional market (address) used when filtering open orders.",
    )


class PlaceOrderInput(BaseModel):
    token_id: str = Field(..., description="Outcome token id (ERC-1155) per market side.")
    side: str = Field(..., description="buy for YES/long, sell for NO/short.")
    size: confloat(gt=0) = Field(..., description="Number of shares to trade.")
    price: confloat(gt=0, le=1) = Field(
        ..., description="Limit price (0-1) expressed as decimal probability."
    )
    order_type: str = Field(
        default="gtc",
        description="Order type string documented in py-clob-client (GTC/FOK/IOC).",
    )
    expiration: int | None = Field(
        default=None,
        description="Unix timestamp; order becomes invalid after this time.",
    )


class CancelOrderInput(BaseModel):
    order_id: str = Field(..., description="Identifier of the order to cancel.")


class ListMarketsInput(BaseModel):
    tag_id: str | None = Field(
        default=None,
        description="Gamma tag identifier, e.g. 100381, per https://docs.polymarket.com/developers/gamma-markets-api/fetch-markets-guide.",
    )
    closed: bool = Field(
        default=False,
        description="Whether to include closed markets. Defaults to only active markets.",
    )
    limit: conint(ge=1, le=100) = Field(
        default=25,
        description="Maximum number of markets per page (Gamma /markets `limit`).",
    )
    offset: conint(ge=0, le=1000) = Field(
        default=0,
        description="Pagination offset (Gamma /markets `offset`).",
    )


class GetMarketPriceInput(BaseModel):
    token_id: str = Field(..., description="Outcome token id whose executable price is needed.")
    side: str = Field(..., description="BUY or SELL as documented in pricing API.")


class GetMarketDetailInput(BaseModel):
    market_id: str = Field(
        ...,
        description=(
            "Gamma market identifier (the numeric id in https://docs.polymarket.com/api-reference/markets/get-market-by-id)."
        ),
    )


def _wrap(client: PolymarketClient, method_name: str) -> Callable:
    method = getattr(client, method_name)

    def _call(**kwargs):
        return method(**kwargs)

    return _call


def build_polymarket_tools(client: PolymarketClient) -> List[StructuredTool]:
    return [
        StructuredTool.from_function(
            name="list_polymarket_orders",
            description=(
                "Use to inspect currently open orders returned by py-clob-client. "
                "Great for prompts like 'query my open orders'."
            ),
            func=_wrap(client, "list_orders"),
            args_schema=ListOrdersInput,
        ),
        StructuredTool.from_function(
            name="list_polymarket_markets",
            description=(
                "Use to call the Gamma /markets endpoint (pagination, tag filters, closed flag)."
            ),
            func=_wrap(client, "list_markets"),
            args_schema=ListMarketsInput,
        ),
        StructuredTool.from_function(
            name="get_polymarket_market_price",
            description=(
                "Use to query https://docs.polymarket.com/api-reference/pricing/get-market-price "
                "for a specific token_id (CLOB token) and side (BUY/SELL)."
            ),
            func=_wrap(client, "get_market_price"),
            args_schema=GetMarketPriceInput,
        ),
        StructuredTool.from_function(
            name="get_polymarket_market_detail",
            description=(
                "Use to fetch a single market's metadata via "
                "https://docs.polymarket.com/api-reference/markets/get-market-by-id."
            ),
            func=_wrap(client, "get_market_detail"),
            args_schema=GetMarketDetailInput,
        ),
        StructuredTool.from_function(
            name="place_polymarket_order",
            description=(
                "Use to submit a new limit order via the Polymarket CLOB. "
                "Requires token id, side (buy/sell), price, and size."
            ),
            func=_wrap(client, "create_order"),
            args_schema=PlaceOrderInput,
        ),
        StructuredTool.from_function(
            name="cancel_polymarket_order",
            description="Use to cancel an existing order by id.",
            func=_wrap(client, "cancel_order"),
            args_schema=CancelOrderInput,
        ),
    ]
