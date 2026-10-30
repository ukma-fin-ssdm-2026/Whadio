import { setupServer } from "msw/node";
import { createOpenApiHttp } from "openapi-msw";
import type { paths } from "../api/schema.gen";

export const server = setupServer();

export const http = createOpenApiHttp<paths>();
