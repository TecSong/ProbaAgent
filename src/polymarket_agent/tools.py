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
    limit: conint(ge=0, le=100) = Field(
        default=25,
        description="Page size (Gamma caps at 100). Mirrors the `limit` query parameter.",
    )
    offset: conint(ge=0, le=1000) = Field(
        default=0,
        description="Pagination offset (0-based) supplied via `offset`.",
    )
    order: str | None = Field(
        default=None,
        description="Field name used for sorting (e.g. `start_date`, `volume_num`).",
    )
    ascending: bool | None = Field(
        default=None,
        description="Set true for ascending order; false for descending.",
    )
    id: List[int] | None = Field(
        default=None,
        description="Restrict results to these numeric market ids.",
    )
    slug: List[str] | None = Field(
        default=None,
        description="Filter by one or more market slugs.",
    )
    clob_token_ids: List[str] | None = Field(
        default=None,
        description="Return markets containing any of these CLOB token ids.",
    )
    condition_ids: List[str] | None = Field(
        default=None,
        description="Filter using UMA condition ids associated with the markets.",
    )
    market_maker_address: List[str] | None = Field(
        default=None,
        description="Limit to markets created by these market maker addresses.",
    )
    liquidity_num_min: confloat(ge=0) | None = Field(
        default=None,
        description="Lower bound for reported market liquidity.",
    )
    liquidity_num_max: confloat(ge=0) | None = Field(
        default=None,
        description="Upper bound for reported market liquidity.",
    )
    volume_num_min: confloat(ge=0) | None = Field(
        default=None,
        description="Lower bound for traded volume.",
    )
    volume_num_max: confloat(ge=0) | None = Field(
        default=None,
        description="Upper bound for traded volume.",
    )
    start_date_min: str | None = Field(
        default=None,
        description="Earliest ISO-8601 start date to include (Gamma `start_date_min`).",
    )
    start_date_max: str | None = Field(
        default=None,
        description="Latest ISO-8601 start date to include.",
    )
    end_date_min: str | None = Field(
        default=None,
        description="Earliest ISO-8601 end date to include.",
    )
    end_date_max: str | None = Field(
        default=None,
        description="Latest ISO-8601 end date to include.",
    )
    tag_id: int | None = Field(
        default=None,
        description="Tag/category identifier documented in the Gamma API.",
    )
    related_tags: bool | None = Field(
        default=None,
        description="Include markets from related tags when true.",
    )
    cyom: bool | None = Field(
        default=None,
        description="Filter to Create-Your-Own-Market listings.",
    )
    uma_resolution_status: str | None = Field(
        default=None,
        description="Filter by UMA resolution status string.",
    )
    game_id: str | None = Field(
        default=None,
        description="Sports `game_id` filter as defined in the API.",
    )
    sports_market_types: List[str] | None = Field(
        default=None,
        description="Filter to specific sports market types (array of strings).",
    )
    rewards_min_size: confloat(ge=0) | None = Field(
        default=None,
        description="Minimum rewards size threshold.",
    )
    question_ids: List[str] | None = Field(
        default=None,
        description="Restrict to markets matching these question ids.",
    )
    include_tag: bool | None = Field(
        default=None,
        description="Include tag metadata alongside markets when true.",
    )
    closed: bool | None = Field(
        default=None,
        description="Include closed markets when true; omit for API default behaviour.",
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
                "Use to call the Gamma /markets endpoint with the documented filters (ids, tags, liquidity, dates, etc.)."
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
