from websocket import WebSocketApp
import certifi
import json
import time
import threading

MARKET_CHANNEL = "market"
USER_CHANNEL = "user"


class WebSocketOrderBook:
    def __init__(self, channel_type, url, data, auth, message_callback, verbose):
        self.channel_type = channel_type
        self.url = url
        self.data = data
        self.auth = auth
        self.message_callback = message_callback
        self.verbose = verbose
        furl = url + "/ws/" + channel_type
        self.ws = WebSocketApp(
            furl,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close,
            on_open=self.on_open,
        )
        self.orderbooks = {}

    def on_message(self, ws, message):
        recv_ts_ms = int(time.time() * 1000)
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            print(message)
            return

        payloads = payload if isinstance(payload, list) else [payload]

        for item in payloads:
            if not isinstance(item, dict):
                continue

            event_ts = item.get("timestamp")
            latency_ms = None
            if event_ts is not None:
                try:
                    latency_ms = recv_ts_ms - int(event_ts)
                    item["_latency_ms"] = latency_ms
                except (ValueError, TypeError):
                    pass

            if self.verbose:
                if latency_ms is not None:
                    print(
                        f"[{self.channel_type}] latency={latency_ms}ms payload={item}"
                    )
                else:
                    print(f"[{self.channel_type}] payload={item}")

            if self.message_callback:
                self.message_callback(item)

    def on_error(self, ws, error):
        print("Error: ", error)
        exit(1)

    def on_close(self, ws, close_status_code, close_msg):
        print("closing")
        exit(0)

    def on_open(self, ws):
        if self.channel_type == MARKET_CHANNEL:
            ws.send(json.dumps({"assets_ids": self.data, "type": MARKET_CHANNEL}))
        elif self.channel_type == USER_CHANNEL and self.auth:
            ws.send(
                json.dumps(
                    {"markets": self.data, "type": USER_CHANNEL, "auth": self.auth}
                )
            )
        else:
            exit(1)

        thr = threading.Thread(target=self.ping, args=(ws,))
        thr.start()

    def ping(self, ws):
        while True:
            ws.send("PING")
            time.sleep(10)

    def run(self):
        self.ws.run_forever(sslopt={"ca_certs": certifi.where()})


if __name__ == "__main__":
    url = "wss://ws-subscriptions-clob.polymarket.com"
    #Complete these by exporting them from your initialized client. 
    import os
    from dotenv import load_dotenv

    load_dotenv()  # 自动加载文件中的环境变量

    api_key = os.environ.get("CLOB_API_KEY")
    api_secret = os.environ.get("CLOB_SECRET")
    api_passphrase = os.environ.get("CLOB_PASS_PHRASE")

    asset_ids = [
        "86792566865618315352054762614265207710146164604619158781420653749604861145936",
    ]
    condition_ids = [] # no really need to filter by this one

    auth = {"apiKey": api_key, "secret": api_secret, "passphrase": api_passphrase}

    market_connection = WebSocketOrderBook(
        MARKET_CHANNEL, url, asset_ids, auth, None, True
    )
    user_connection = WebSocketOrderBook(
        USER_CHANNEL, url, condition_ids, auth, None, True
    )

    market_connection.run()
    # user_connection.run()