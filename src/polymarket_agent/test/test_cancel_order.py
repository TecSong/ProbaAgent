from polymarket_agent.main import build_client_from_env
from polymarket_agent.client import PolymarketClientError
from dotenv import load_dotenv
load_dotenv()


def main():
    client = build_client_from_env()
    response = client.cancel_order(
        order_id="0x19ac160afeefaae57a8ac60bb7d76ff3fc8797f1238cfbf0614a7b049ca3e805"
    )
    print(response)

    # order = client._client.get_order(order_id="0x19ac160afeefaae57a8ac60bb7d76ff3fc8797f1238cfbf0614a7b049ca3e805")
    # print(order)
    # trades = client._client.get_trades()
    # print(trades)

if __name__ == "__main__":
    main()