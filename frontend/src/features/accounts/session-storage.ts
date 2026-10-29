import { z } from "zod";
import type { Schemas } from "@/shared/api/types";

const STORAGE_KEY = "whadio-user";

export type SignedInUser = Pick<Schemas["UserRead"], "id" | "email" | "name">;

const signedInUser: z.ZodType<SignedInUser> = z.object({
  id: z.string(),
  email: z.string(),
  name: z.string(),
});

export function readSignedInUser(): SignedInUser | null {
  const stored = sessionStorage.getItem(STORAGE_KEY);
  if (stored === null) return null;
  try {
    const parsed = signedInUser.safeParse(JSON.parse(stored));
    return parsed.success ? parsed.data : null;
  } catch {
    return null;
  }
}

export function storeSignedInUser({ id, email, name }: SignedInUser): void {
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ id, email, name }));
}

export function clearSignedInUser(): void {
  sessionStorage.removeItem(STORAGE_KEY);
}
