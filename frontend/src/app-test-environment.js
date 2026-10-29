import { JSDOM } from "jsdom";
import { createServer } from "vite";

export async function openAppEnvironment(url) {
  const dom = new JSDOM('<div id="root"></div>', { url, pretendToBeVisual: true });
  const globals = {
    window: dom.window,
    document: dom.window.document,
    navigator: dom.window.navigator,
    HTMLElement: dom.window.HTMLElement,
    DocumentFragment: dom.window.DocumentFragment,
    Node: dom.window.Node,
    sessionStorage: dom.window.sessionStorage,
    getComputedStyle: dom.window.getComputedStyle.bind(dom.window),
    IS_REACT_ACT_ENVIRONMENT: true,
  };
  const savedGlobals = new Map();
  for (const [name, value] of Object.entries(globals)) {
    savedGlobals.set(name, Object.getOwnPropertyDescriptor(globalThis, name));
    Object.defineProperty(globalThis, name, { configurable: true, writable: true, value });
  }
  // React DOM detects the browser when it is first imported, so the globals must exist before.
  const { act, createElement } = await import("react");
  const { createRoot } = await import("react-dom/client");
  const server = await createServer({
    server: { middlewareMode: true, watch: null, ws: false },
    appType: "custom",
    optimizeDeps: { noDiscovery: true },
    ssr: { noExternal: ["@mui/icons-material"] },
  });
  const app = await server.ssrLoadModule("/src/main.jsx");
  return {
    app,
    act,
    createElement,
    createRoot,
    async close() {
      await server.close();
      dom.window.close();
      for (const [name, descriptor] of savedGlobals) {
        if (descriptor) Object.defineProperty(globalThis, name, descriptor);
        else Reflect.deleteProperty(globalThis, name);
      }
    },
  };
}
