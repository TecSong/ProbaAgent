import os

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, OrderArgs
from dotenv import load_dotenv
from py_clob_client.constants import AMOY

from py_clob_client.order_builder.constants import BUY


load_dotenv()


def main():
    host = os.getenv("CLOB_API_URL", "https://clob.polymarket.com")
    key = os.getenv("POLYMARKET_PRIVATE_KEY", '')
    # creds = ApiCreds(
    #     api_key=os.getenv("POLYMARKET_PRIVATE_KEY", ''),
    #     api_secret=os.getenv("CLOB_SECRET"),
    #     api_passphrase=os.getenv("CLOB_PASS_PHRASE"),
    # )
    chain_id = AMOY
    client = ClobClient(host, key=key, chain_id=chain_id)
    client.set_api_creds(client.create_or_derive_api_creds())

    # Create and sign a limit order buying 100 YES tokens for 0.0005 each
    order_args = OrderArgs(
        token_id="81104637750588840860328515305303028259865221573278091453716127842023614249200",
        side="BUY",
        size=2.0,
        price=0.985
    )
    signed_order = client.create_order(order_args)
    resp = client.post_order(signed_order)
    print(resp)
    print("Done!")


main()