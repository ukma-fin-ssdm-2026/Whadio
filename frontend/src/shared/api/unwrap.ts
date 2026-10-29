import { ApiError, NETWORK_ERROR } from "./errors";

type FetchResult<T> = { data?: T; error?: unknown; response: Response };

async function settle<T>(request: Promise<FetchResult<T>>): Promise<FetchResult<T>> {
  try {
    return await request;
  } catch (cause) {
    throw new ApiError({
      status: 0,
      code: NETWORK_ERROR,
      message: "Could not reach the server. Check your connection and try again.",
      cause,
    });
  }
}

export async function unwrap<T>(request: Promise<FetchResult<T>>): Promise<T> {
  const { data, error, response } = await settle(request);
  if (!response.ok || data === undefined) throw ApiError.from(response, error);
  return data;
}

export async function expectNoContent(request: Promise<FetchResult<unknown>>): Promise<void> {
  const { error, response } = await settle(request);
  if (!response.ok) throw ApiError.from(response, error);
}
