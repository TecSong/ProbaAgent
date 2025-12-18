import { useCallback, useEffect, useMemo, useState } from "react";
import { ethers } from "ethers";
import {
  useAppKit,
  useAppKitAccount,
  useAppKitNetwork,
  useAppKitProvider,
  useDisconnect,
} from "@reown/appkit/react";
import { polygon } from "@reown/appkit/networks";

const DEFAULT_NETWORK = polygon;

const EXPECTED_CHAIN_ID = (() => {
  const raw = import.meta.env.VITE_EXPECTED_CHAIN_ID;
  const fallback = DEFAULT_NETWORK.id;
  if (raw === undefined || raw === null || raw === "") return fallback;
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : fallback;
})();

const EXPECTED_NETWORK_NAME = import.meta.env.VITE_EXPECTED_NETWORK_NAME || DEFAULT_NETWORK.name;

export function useWalletState() {
  const { open } = useAppKit();
  const { disconnect } = useDisconnect();
  const { address, isConnected, status } = useAppKitAccount();
  const { caipNetwork, chainId, switchNetwork } = useAppKitNetwork();
  const { walletProvider } = useAppKitProvider("eip155");

  const [balance, setBalance] = useState(null);
  const [isFetchingBalance, setIsFetchingBalance] = useState(false);
  const [isSwitching, setIsSwitching] = useState(false);
  const [isDisconnecting, setIsDisconnecting] = useState(false);
  const [isOpeningModal, setIsOpeningModal] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const loadBalance = async () => {
      if (!isConnected || !walletProvider || !address) {
        if (!cancelled) setBalance(null);
        return;
      }
      setIsFetchingBalance(true);
      try {
        const provider = new ethers.BrowserProvider(walletProvider);
        const value = await provider.getBalance(address);
        if (!cancelled) setBalance(value);
      } catch (error) {
        console.warn("Failed to fetch wallet balance:", error);
        if (!cancelled) setBalance(null);
      } finally {
        if (!cancelled) setIsFetchingBalance(false);
      }
    };

    loadBalance();

    return () => {
      cancelled = true;
    };
  }, [walletProvider, isConnected, address, chainId]);

  const handleConnect = useCallback(async () => {
    try {
      setIsOpeningModal(true);
      await open({ view: "Connect" });
    } catch (error) {
      console.error("Failed to open wallet connect modal:", error);
    } finally {
      setIsOpeningModal(false);
    }
  }, [open]);

  const handleDisconnect = useCallback(async () => {
    setIsDisconnecting(true);
    try {
      await disconnect();
    } catch (error) {
      console.warn("Failed to disconnect wallet:", error);
    } finally {
      setIsDisconnecting(false);
    }
  }, [disconnect]);

  const handleSwitchNetwork = useCallback(async () => {
    if (!switchNetwork) return;
    setIsSwitching(true);
    try {
      await switchNetwork(DEFAULT_NETWORK);
    } catch (error) {
      console.error("Failed to switch network:", error);
    } finally {
      setIsSwitching(false);
    }
  }, [switchNetwork]);

  const wallet = useMemo(() => {
    const derivedChainId = chainId ?? caipNetwork?.chainId ?? caipNetwork?.id ?? null;

    return {
      address: address || null,
      isConnected,
      balance,
      chainId: derivedChainId,
      network: caipNetwork || null,
    };
  }, [address, isConnected, balance, chainId, caipNetwork]);

  const isConnecting = status === "connecting" || isOpeningModal;

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
    isFetchingBalance,
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
