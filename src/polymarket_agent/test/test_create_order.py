from polymarket_agent.main import build_client_from_env
from polymarket_agent.client import PolymarketClientError
from dotenv import load_dotenv
load_dotenv()


def main():
    client = build_client_from_env()
    # response = client.create_order(
    #     token_id="87769991026114894163580777793845523168226980076553814689875238288185044414090",
    #     side="BUY",
    #     size=5.0,
    #     price=0.68
    # )
    # print(response)

    # order = client._client.get_order(order_id="0x27b0fbdac2090ca28326da04278e061c7df0247fe410a47d8b46157254491542")
    # print(order)
    trades = client._client.get_trades()
    print(trades)

if __name__ == "__main__":
    main()