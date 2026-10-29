// The generated types keep a request's media type out of the runtime, so a Blob field is what
// marks a multipart body.
export function serializeBody(body: unknown): FormData | string {
  if (body instanceof FormData) return body;
  if (typeof body !== "object" || body === null) return JSON.stringify(body);
  const fields: [string, unknown][] = Object.entries(body);
  if (!fields.some(([, value]) => value instanceof Blob)) return JSON.stringify(body);
  const form = new FormData();
  for (const [key, value] of fields) {
    if (value instanceof Blob || typeof value === "string") form.append(key, value);
    else if (value !== undefined && value !== null) form.append(key, JSON.stringify(value));
  }
  return form;
}
