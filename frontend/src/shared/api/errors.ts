import { z } from "zod";
import { type components, errorCodeValues } from "./schema.gen";

type ErrorDetail = components["schemas"]["ErrorDetail"];

export const UNEXPECTED_RESPONSE = "UNEXPECTED_RESPONSE";
export const NETWORK_ERROR = "NETWORK_ERROR";

export type ApiErrorCode =
  | components["schemas"]["ErrorCode"]
  | typeof UNEXPECTED_RESPONSE
  | typeof NETWORK_ERROR;

const errorDetail: z.ZodType<ErrorDetail> = z.object({
  field: z.string().nullable(),
  message: z.string(),
  provided_value: z.unknown().optional(),
});

const errorEnvelope = z.object({
  error: z.object({
    code: z.enum(errorCodeValues),
    message: z.string(),
    details: z.array(errorDetail).default([]),
    request_id: z.string(),
  }),
});

type ApiErrorInit = {
  status: number;
  code: ApiErrorCode;
  message: string;
  details?: readonly ErrorDetail[];
  requestId?: string;
  cause?: unknown;
};

export class ApiError extends Error {
  override readonly name = "ApiError";
  readonly status: number;
  readonly code: ApiErrorCode;
  readonly details: readonly ErrorDetail[];
  readonly requestId: string | undefined;

  constructor({ status, code, message, details = [], requestId, cause }: ApiErrorInit) {
    super(message, { cause });
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
  }

  static from(response: Response, body: unknown): ApiError {
    const envelope = errorEnvelope.safeParse(body);
    if (!envelope.success) {
      return new ApiError({
        status: response.status,
        code: UNEXPECTED_RESPONSE,
        message: `Request failed (${response.status})`,
      });
    }
    const { code, message, details, request_id } = envelope.data.error;
    return new ApiError({ status: response.status, code, message, details, requestId: request_id });
  }
}
