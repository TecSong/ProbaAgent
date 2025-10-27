export default function ChatMessage({ role, content }) {
  const displayRole = role === "assistant" ? "Agent" : "You";
  return (
    <div className={`message ${role}`}>
      <div className="message-avatar">{displayRole[0]}</div>
      <div className="message-body">
        <strong>{displayRole}</strong>
        <div>{content}</div>
      </div>
    </div>
  );
}
