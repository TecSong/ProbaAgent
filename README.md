## 简介

该项目演示如何基于 LangChain 与 Polymarket 官方 `py-clob-client`（参考 https://github.com/polymarket/py-clob-client ）构建一个可以用自然语言完成「查看订单 / 下订单 / 取消订单」的智能体。所有接口约定均来自 Context7 获取的官方文档，保证与最新 CLOB API 一致。

## 快速开始

1. **安装依赖**
   ```bash
   pip install -r requirements.txt
   ```
2. **配置环境变量**  
   拷贝 `.env.example` 为 `.env` 并填写：
   - `OPENAI_API_KEY`：LangChain 使用的 LLM（默认 gpt-4o-mini）。
   - `POLYMARKET_HOST`：CLOB 入口，来自 py-clob-client 文档（默认 `https://clob.polymarket.com`）。
   - `POLYMARKET_CHAIN_ID`、`POLYMARKET_SIGNATURE_TYPE`：链 ID 与签名方式，Polygon 主网建议 `137` 和 `0`。
   - `POLYMARKET_PRIVATE_KEY`：用于签名订单的钱包私钥（请妥善保管）。
   - `POLYMARKET_FUNDER`：可选，邮件/Magic 钱包用户需提供资方地址。
   - `POLYMARKET_GAMMA_BASE`：Gamma Markets API 基础地址（默认 `https://gamma-api.polymarket.com`），用于查询市场列表。
   - `POLYMARKET_DEBUG`：设置为 `true`/`1` 时会开启调试模式，输出订单 payload 与 Gamma 调用日志，便于排查问题。
3. **运行交互式 CLI**
   ```bash
   python -m polymarket_agent.main --verbose
   ```
   在提示符中输入 “帮我查看市场 xxx 的未成交订单”等自然语言指令即可。

## 架构说明

- `polymarket_agent.client.PolymarketClient`：对 py-clob-client 的轻量封装，并额外封装 Gamma `/markets` 接口，实现市场列表查询。
- `polymarket_agent.tools.build_polymarket_tools`：将客户端方法包装成 LangChain `StructuredTool`，包括“查订单 / 列市场 / 查市场详情 / 查价格 / 下单 / 撤单”等操作，参数遵循官方文档。
- `polymarket_agent.agent.build_polymarket_agent`：参考 https://docs.langchain.com/oss/python/langchain/agents 的最新 `create_agent` 流程，直接以 LangChain 官方 Agent API 管理工具调用。
- `polymarket_agent.main`：简单 CLI 循环，维护对话历史，便于连续多轮操作。

## 进一步扩展

1. 支持行情、资产、资金划转等更多 Polymarket 端点，并暴露为新工具。
2. 接入检索增强（RAG），将市场元数据、策略提示等知识喂给系统消息。
3. 在服务端封装为 REST/gRPC/Slack Bot，以支持多终端调用。
4. 为关键路径编写集成测试，使用 VCR/pytest-httpx 之类的工具回放 Polymarket 响应。
