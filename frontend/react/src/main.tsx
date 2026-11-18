import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";
import "@fontsource-variable/inter/wght.css";
import "@fontsource/cinzel/latin-700.css";
import "./v3/v3.css";

document.documentElement.classList.add("ax-v3");

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
