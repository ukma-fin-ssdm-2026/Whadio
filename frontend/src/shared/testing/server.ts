import { setupServer } from "msw/node";
import { createOpenApiHttp } from "openapi-msw";
import type { paths } from "../api/schema.gen";

export const http = createOpenApiHttp<paths>();

export const server = setupServer(
  http.get("/api/v1/instance", ({ response }) =>
    response(200).json({ registration_mode: "invite-only", api_version: "1" }),
  ),
);
