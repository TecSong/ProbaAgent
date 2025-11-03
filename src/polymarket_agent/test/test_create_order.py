from polymarket_agent.main import build_client_from_env
from polymarket_agent.client import PolymarketClientError
from dotenv import load_dotenv
load_dotenv()

client = build_client_from_env()

# client.update_balance_allowance(
#     token_id="81104637750588840860328515305303028259865221573278091453716127842023614249200"
# )

response = client.create_order(
    # token_id="81104637750588840860328515305303028259865221573278091453716127842023614249200",
    token_id="87769991026114894163580777793845523168226980076553814689875238288185044414090",
    side="SELL",
    size=5.0,
    price=0.68
    )

print(response)