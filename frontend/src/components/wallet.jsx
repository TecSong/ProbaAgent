import { useState } from "react";
import { ethers } from "ethers";

const initWallet = {
  address: null,
  isConnected: false,
  balance: 0,
  chainId: null,
  network: null,
};

export default function WalletConnector() {
  const [wallet, setWallet] = useState(initWallet);
  const [isConnecting, setIsConnecting] = useState(false);

  const handleConnect = async () => {
    if (!window.ethereum) {
      alert("No wallet detected. Please install MetaMask or another Ethereum wallet.");
      return;
    }

    try {
      setIsConnecting(true);

      const provider = new ethers.BrowserProvider(window.ethereum);
      const accounts = await provider.send("eth_requestAccounts", []);

      const network = await provider.getNetwork();
      const balance = await provider.getBalance(accounts[0]);

      setWallet((prev) => ({
        ...prev,
        address: accounts[0],
        balance,
        network,
        chainId: network.chainId,
        isConnected: true,
      }));
    } catch (error) {
      console.error("Failed to connect wallet:", error);
    } finally {
      setIsConnecting(false);
    }
  };

  const handleDisconnect = () => {
    setWallet(initWallet);
  };

  if (wallet.isConnected && wallet.address) {
    return (
      <div className="wallet-controls">
        <button className="wallet-button wallet-button--connected" type="button" disabled>
          {`${wallet.address.slice(0, 6)}...${wallet.address.slice(-4)}`}
        </button>
        <button
          className="wallet-button wallet-button--secondary"
          type="button"
          onClick={handleDisconnect}
        >
          Disconnect
        </button>
      </div>
    );
  }

  return (
    <button
      className="wallet-button"
      type="button"
      onClick={handleConnect}
      disabled={isConnecting}
    >
      {isConnecting ? "Connecting..." : "Connect Wallet"}
    </button>
  );
}