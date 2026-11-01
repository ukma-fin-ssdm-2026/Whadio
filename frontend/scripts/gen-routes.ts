import { fileURLToPath } from "node:url";
import { Generator, getConfig } from "@tanstack/router-generator";

const ROOT = fileURLToPath(new URL("..", import.meta.url));

// The Vite plugin reads tsr.config.json as well. Its empty `routeTreeFileHeader` replaces a default
// that turns type checking off, a suppression the commit hook refuses.
await new Generator({ config: getConfig({}, ROOT), root: ROOT }).run();
