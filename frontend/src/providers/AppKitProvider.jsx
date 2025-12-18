import { AppKitProvider } from "@reown/appkit/react";
import { polygon } from "@reown/appkit/networks";

const projectId = import.meta.env.VITE_REOWN_PROJECT_ID;

const metadata = {
  name: "Polymarket Chatbot",
  description: "Chat with a Polymarket agent and manage trades.",
  url: typeof window !== "undefined" ? window.location.origin : "http://localhost",
  icons: ["https://assets.reown.com/reown-profile-pic.png"],
};

export default function ReownProvider({ children }) {
  if (!projectId) {
    // AppKit requires a WalletConnect/Reown project ID; warn early if it is missing.
    console.warn("Missing VITE_REOWN_PROJECT_ID. AppKit will not be able to connect wallets.");
  }

  return (
    <AppKitProvider
      projectId={projectId || "missing-project-id"}
      networks={[polygon]}
      defaultNetwork={polygon}
      metadata={metadata}
      enableEIP6963
      enableInjected
      enableWalletConnect
      allWallets="SHOW"
    >
      {children}
    </AppKitProvider>
  );
}
