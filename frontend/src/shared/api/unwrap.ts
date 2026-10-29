import { ApiError } from "./errors";

type FetchResult<T> = { data?: T; error?: unknown; response: Response };

export async function unwrap<T>(request: Promise<FetchResult<T>>): Promise<T> {
  const { data, error, response } = await request;
  if (!response.ok || data === undefined) throw ApiError.from(response, error);
  return data;
}

export async function expectNoContent(request: Promise<FetchResult<unknown>>): Promise<void> {
  const { error, response } = await request;
  if (!response.ok) throw ApiError.from(response, error);
}
