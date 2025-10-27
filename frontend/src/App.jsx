import { useEffect, useRef, useState } from "react";
import axios from "axios";

import ChatMessage from "./components/ChatMessage.jsx";

const API_BASE = import.meta.env.VITE_API_BASE || "/api";

export default function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [status, setStatus] = useState("Ready");
  const [error, setError] = useState("");
  const feedRef = useRef(null);

  useEffect(() => {
    if (feedRef.current) {
      feedRef.current.scrollTop = feedRef.current.scrollHeight;
    }
  }, [messages]);

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (isSending) {
      return;
    }
    const trimmed = input.trim();
    if (!trimmed) {
      return;
    }

    const previousHistory = messages;
    const optimisticHistory = [...previousHistory, { role: "user", content: trimmed }];

    setMessages(optimisticHistory);
    setInput("");
    setIsSending(true);
    setStatus("Contacting agent…");
    setError("");

    try {
      const { data } = await axios.post(`${API_BASE}/chat`, {
        message: trimmed,
        history: previousHistory
      });
      setMessages(data.history || optimisticHistory);
      setStatus("Ready");
    } catch (err) {
      const fallback =
        err?.response?.data?.error || err.message || "Failed to contact the agent.";
      setError(fallback);
      setStatus("Error");
      setMessages(optimisticHistory);
    } finally {
      setIsSending(false);
    }
  };

  const placeholder =
    "Ask about your open orders, place a trade, or inspect markets. Shift+Enter for a new line.";

  return (
    <div className="chat-shell">
      <header className="chat-header">
        <h1>Polymarket Chatbot</h1>
        <p>Talk to a LangChain-powered assistant backed by the Polymarket CLOB.</p>
      </header>

      <section className="chat-feed" ref={feedRef}>
        {messages.length === 0 && (
          <div className="message assistant">
            <div className="message-avatar">A</div>
            <div className="message-body">
              <strong>Agent</strong>
              <div>
                Hello! I can list markets, fetch quotes, place orders, or cancel trades on
                Polymarket. What would you like to do?
              </div>
            </div>
          </div>
        )}
        {messages.map((message, index) => (
          <ChatMessage key={`${message.role}-${index}`} {...message} />
        ))}
      </section>

      <div className="chat-form">
        <form onSubmit={handleSubmit}>
          <textarea
            value={input}
            placeholder={placeholder}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                handleSubmit(event);
              }
            }}
            disabled={isSending}
          />
          <button type="submit" disabled={isSending}>
            {isSending ? "Thinking…" : "Send"}
          </button>
        </form>
        <div className={`status-bar ${error ? "error" : ""}`}>
          {error ? error : status}
        </div>
      </div>
    </div>
  );
}
