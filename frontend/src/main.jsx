import React from "react";
import ReactDOM from "react-dom/client";

import App from "./App.jsx";
import "./styles.css";
import ReownProvider from "./providers/AppKitProvider.jsx";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <ReownProvider>
      <App />
    </ReownProvider>
  </React.StrictMode>
);
