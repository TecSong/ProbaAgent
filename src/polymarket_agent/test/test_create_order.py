from polymarket_agent.main import build_client_from_env
from polymarket_agent.client import PolymarketClientError
from dotenv import load_dotenv
load_dotenv()

client = build_client_from_env()
# order_type = "gtc"
response = client.create_order(
    token_id="81104637750588840860328515305303028259865221573278091453716127842023614249200",
    # token_id="114304586861386186441621124384163963092522056897081085884483958561365015034812",
    side="BUY",
    size=2.0,
    price=0.985
    )

print(response)