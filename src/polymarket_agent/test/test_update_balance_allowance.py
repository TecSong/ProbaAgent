
from dotenv import load_dotenv
load_dotenv()
import os
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, BalanceAllowanceParams, AssetType
from dotenv import load_dotenv
from py_clob_client.constants import AMOY, POLYGON
from web3 import Web3
from web3.constants import MAX_INT
from web3.middleware import ExtraDataToPOAMiddleware
from src.polymarket_agent.test.approve_abi import erc20_approve, erc1155_set_approval
load_dotenv()


def main():
    _init_approvals()

def check_balance_and_allowance():
    host = os.getenv("CLOB_API_URL", "https://clob.polymarket.com")
    key = os.getenv("POLYMARKET_PRIVATE_KEY")
    # funder = os.getenv("POLYMARKET_FUNDER")
    # creds = ApiCreds(
    #     api_key=os.getenv("CLOB_API_KEY"),
    #     api_secret=os.getenv("CLOB_SECRET"),
    #     api_passphrase=os.getenv("CLOB_PASS_PHRASE"),
    # )
    chain_id = POLYGON
    client = ClobClient(host, key=key, chain_id=chain_id)
    client.set_api_creds(client.create_or_derive_api_creds())

    # print('creds ', client.creds)
    # response = client.get_api_keys()
    # print(response)

    

    # USDC
    # response = client.update_balance_allowance(
    #     params=BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
    # )
    # print(response)

    response = client.get_balance_allowance(
        params=BalanceAllowanceParams(asset_type=AssetType.COLLATERAL))
    print(response)

    # YES
    # client.update_balance_allowance(
    #     params=BalanceAllowanceParams(
    #         asset_type=AssetType.CONDITIONAL,
    #         token_id="52114319501245915516055106046884209969926127482827954674443846427813813222426",
    #     )
    # )

    # # NO
    # client.update_balance_allowance(
    #     params=BalanceAllowanceParams(
    #         asset_type=AssetType.CONDITIONAL,
    #         token_id="71321045679252212594626385532706912750332728571942532289631379312455583992563",
    #     )
    # )


def _init_approvals() -> None:
    # gamma_url = "https://gamma-api.polymarket.com"
    # gamma_markets_endpoint = gamma_url + "/markets"
    # gamma_events_endpoint = gamma_url + "/events"

    # clob_url = "https://clob.polymarket.com"
    # clob_auth_endpoint = clob_url + "/auth/api-key"

    chain_id = 137  # POLYGON
    priv_key = os.getenv("POLYMARKET_PRIVATE_KEY")
    polygon_rpc = "https://polygon-rpc.com"
    w3 = Web3(Web3.HTTPProvider(polygon_rpc))

    # exchange_address = "0x4bfb41d5b3570defd03c39a9a4d8de6bd8b8982e"
    # neg_risk_exchange_address = "0xC5d563A36AE78145C45a50134d48A1215220f80a"

    usdc_address = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
    ctf_address = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"

    web3 = Web3(Web3.HTTPProvider(polygon_rpc))
    web3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

    usdc = web3.eth.contract(
        address=usdc_address, abi=erc20_approve
    )
    ctf = web3.eth.contract(
        address=ctf_address, abi=erc1155_set_approval
    )

    pub_key = w3.eth.account.from_key(str(priv_key)).address
    nonce = web3.eth.get_transaction_count(pub_key)

    # CTF Exchange
    raw_usdc_approve_txn = usdc.functions.approve(
        "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E", int(MAX_INT, 0)
    ).build_transaction({"chainId": chain_id, "from": pub_key, "nonce": nonce})
    signed_usdc_approve_tx = web3.eth.account.sign_transaction(
        raw_usdc_approve_txn, private_key=priv_key
    )
    send_usdc_approve_tx = web3.eth.send_raw_transaction(
        signed_usdc_approve_tx.raw_transaction
    )
    usdc_approve_tx_receipt = web3.eth.wait_for_transaction_receipt(
        send_usdc_approve_tx, 600
    )
    print(usdc_approve_tx_receipt)

    nonce = web3.eth.get_transaction_count(pub_key)

    raw_ctf_approval_txn = ctf.functions.setApprovalForAll(
        "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E", True
    ).build_transaction({"chainId": chain_id, "from": pub_key, "nonce": nonce})
    signed_ctf_approval_tx = web3.eth.account.sign_transaction(
        raw_ctf_approval_txn, private_key=priv_key
    )
    send_ctf_approval_tx = web3.eth.send_raw_transaction(
        signed_ctf_approval_tx.raw_transaction
    )
    ctf_approval_tx_receipt = web3.eth.wait_for_transaction_receipt(
        send_ctf_approval_tx, 600
    )
    print(ctf_approval_tx_receipt)

    nonce = web3.eth.get_transaction_count(pub_key)

    # Neg Risk CTF Exchange
    raw_usdc_approve_txn = usdc.functions.approve(
        "0xC5d563A36AE78145C45a50134d48A1215220f80a", int(MAX_INT, 0)
    ).build_transaction({"chainId": chain_id, "from": pub_key, "nonce": nonce})
    signed_usdc_approve_tx = web3.eth.account.sign_transaction(
        raw_usdc_approve_txn, private_key=priv_key
    )
    send_usdc_approve_tx = web3.eth.send_raw_transaction(
        signed_usdc_approve_tx.raw_transaction
    )
    usdc_approve_tx_receipt = web3.eth.wait_for_transaction_receipt(
        send_usdc_approve_tx, 600
    )
    print(usdc_approve_tx_receipt)

    nonce = web3.eth.get_transaction_count(pub_key)

    raw_ctf_approval_txn = ctf.functions.setApprovalForAll(
        "0xC5d563A36AE78145C45a50134d48A1215220f80a", True
    ).build_transaction({"chainId": chain_id, "from": pub_key, "nonce": nonce})
    signed_ctf_approval_tx = web3.eth.account.sign_transaction(
        raw_ctf_approval_txn, private_key=priv_key
    )
    send_ctf_approval_tx = web3.eth.send_raw_transaction(
        signed_ctf_approval_tx.raw_transaction
    )
    ctf_approval_tx_receipt = web3.eth.wait_for_transaction_receipt(
        send_ctf_approval_tx, 600
    )
    print(ctf_approval_tx_receipt)

    nonce = web3.eth.get_transaction_count(pub_key)

    # Neg Risk Adapter
    raw_usdc_approve_txn = usdc.functions.approve(
        "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296", int(MAX_INT, 0)
    ).build_transaction({"chainId": chain_id, "from": pub_key, "nonce": nonce})
    signed_usdc_approve_tx = web3.eth.account.sign_transaction(
        raw_usdc_approve_txn, private_key=priv_key
    )
    send_usdc_approve_tx = web3.eth.send_raw_transaction(
        signed_usdc_approve_tx.raw_transaction
    )
    usdc_approve_tx_receipt = web3.eth.wait_for_transaction_receipt(
        send_usdc_approve_tx, 600
    )
    print(usdc_approve_tx_receipt)

    nonce = web3.eth.get_transaction_count(pub_key)

    raw_ctf_approval_txn = ctf.functions.setApprovalForAll(
        "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296", True
    ).build_transaction({"chainId": chain_id, "from": pub_key, "nonce": nonce})
    signed_ctf_approval_tx = web3.eth.account.sign_transaction(
        raw_ctf_approval_txn, private_key=priv_key
    )
    send_ctf_approval_tx = web3.eth.send_raw_transaction(
        signed_ctf_approval_tx.raw_transaction
    )
    ctf_approval_tx_receipt = web3.eth.wait_for_transaction_receipt(
        send_ctf_approval_tx, 600
    )
    print(ctf_approval_tx_receipt)

main()