import { createRoot } from "react-dom/client";
import { App } from "./App";

const container = document.getElementById("root");
if (!container) throw new Error("The page has no #root element to mount the app into.");
createRoot(container).render(<App />);
