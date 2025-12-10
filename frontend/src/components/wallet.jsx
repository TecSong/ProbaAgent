import { useState } from "react";
import { ethers } from "ethers";

const initWallet = {
  address: null,
  isConnected: false,
  balance: 0,
  chainId: null,
  network: null,
};

const EXPECTED_CHAIN_ID = (() => {
  const raw = import.meta.env.VITE_EXPECTED_CHAIN_ID;
  if (raw === undefined || raw === null || raw === "") return 137; // default to Polygon
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : 137;
})();

const EXPECTED_NETWORK_NAME = import.meta.env.VITE_EXPECTED_NETWORK_NAME || "Polygon";

export function useWalletState() {
    const [wallet, setWallet] = useState(initWallet);
    const [isConnecting, setIsConnecting] = useState(false);
    const [isDisconnecting, setIsDisconnecting] = useState(false);
    const [isSwitching, setIsSwitching] = useState(false);
  
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
    
    const handleSwitchNetwork = async () => {
        if (!window.ethereum) {
          alert("No wallet detected. Please install MetaMask or another Ethereum wallet.");
          return;
        }
        if (!EXPECTED_CHAIN_ID) return;
        try {
          setIsSwitching(true);
          await window.ethereum.request({
            method: "wallet_switchEthereumChain",
            params: [{ chainId: `0x${EXPECTED_CHAIN_ID.toString(16)}` }],
          });
          await handleConnect();
        } catch (error) {
          console.error("Failed to switch network:", error);
        } finally {
          setIsSwitching(false);
        }
      };
    
    const handleDisconnect = async () => {
        setIsDisconnecting(true);
        try {
            if (window.ethereum?.request) {
            // Ask the wallet to revoke permissions so it disconnects from every chain session.
            await window.ethereum.request({
                method: "wallet_revokePermissions",
                params: [{ eth_accounts: {} }],
            });
            }
        } catch (err) {
            console.warn("Wallet refused to revoke permissions:", err);
        } finally {
            setWallet({...initWallet});
            setIsDisconnecting(false);
        }
    };
  
    return {
      wallet,
      isConnecting,
      isDisconnecting,
      isSwitching,
      expectedChainId: EXPECTED_CHAIN_ID,
      expectedNetworkName: EXPECTED_NETWORK_NAME,
      handleConnect,
      handleDisconnect,
      handleSwitchNetwork,
    };
  }

export default function WalletConnector({
  wallet,
  isConnecting,
  isDisconnecting,
  isSwitching,
  expectedChainId,
  expectedNetworkName,
  handleConnect,
  handleDisconnect,
  handleSwitchNetwork,
}) {
  const chainIdNum = wallet.chainId != null ? Number(wallet.chainId) : null;
  const chainName = wallet.network?.name || (chainIdNum ? `Chain ${chainIdNum}` : "Unknown");
  const formattedBalance =
    wallet.balance !== null && wallet.balance !== undefined
      ? ethers.formatEther(wallet.balance)
      : null;
  const shortBalance =
    formattedBalance && !Number.isNaN(Number.parseFloat(formattedBalance))
      ? Number.parseFloat(formattedBalance).toFixed(3)
      : null;
  const isMismatchedNetwork =
    wallet.isConnected && expectedChainId && chainIdNum && chainIdNum !== expectedChainId;
  const isBusy = isConnecting || isDisconnecting || isSwitching;

  return (
    <div className="wallet-panel">
      <div className="wallet-meta">
        <div className="wallet-meta__item">
          <span className="wallet-meta__label">Network</span>
          <span className={`wallet-pill ${isMismatchedNetwork ? "wallet-pill--warn" : ""}`}>
            {wallet.isConnected ? chainName : "Not connected"}
            {chainIdNum ? ` · #${chainIdNum}` : ""}
          </span>
          {isMismatchedNetwork && (
            <span className="wallet-expected">
              Expected {expectedNetworkName} (#{expectedChainId})
            </span>
          )}
        </div>
        <div className="wallet-meta__item">
          <span className="wallet-meta__label">Balance</span>
          <span className="wallet-balance">
            {wallet.isConnected ? (shortBalance ? `${shortBalance} ETH` : "--") : "--"}
          </span>
        </div>
      </div>

      <div className="wallet-controls">
        {wallet.isConnected && wallet.address ? (
          <>
            <button className="wallet-button wallet-button--connected" type="button" disabled>
              {`${wallet.address.slice(0, 6)}...${wallet.address.slice(-4)}`}
            </button>
            {isMismatchedNetwork && (
              <button
                className="wallet-button wallet-button--secondary wallet-button--warning"
                type="button"
                onClick={handleSwitchNetwork}
                disabled={isBusy}
              >
                {isSwitching ? "Switching..." : `Switch to ${expectedNetworkName}`}
              </button>
            )}
            <button
              className="wallet-button wallet-button--secondary"
              type="button"
              onClick={handleDisconnect}
              disabled={isBusy}
            >
              {isDisconnecting ? "Disconnecting..." : "Disconnect"}
            </button>
          </>
        ) : (
          <button
            className="wallet-button"
            type="button"
            onClick={handleConnect}
            disabled={isConnecting || isSwitching}
          >
            {isConnecting ? "Connecting..." : "Connect Wallet"}
          </button>
        )}
      </div>
    </div>
  );
}
