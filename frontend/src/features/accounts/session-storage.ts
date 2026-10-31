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
  try {
    const stored = sessionStorage.getItem(STORAGE_KEY);
    if (stored === null) return null;
    const parsed = signedInUser.safeParse(JSON.parse(stored));
    return parsed.success ? parsed.data : null;
  } catch {
    return null;
  }
}

// The session lives in a cookie and this copy only names the user, so denied or full storage
// must not fail the sign-in or sign-out around it.
function ignoringStorageFailure(write: () => void): void {
  try {
    write();
  } catch {
    return;
  }
}

export function storeSignedInUser({ id, email, name }: SignedInUser): void {
  ignoringStorageFailure(() =>
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ id, email, name })),
  );
}

export function clearSignedInUser(): void {
  ignoringStorageFailure(() => sessionStorage.removeItem(STORAGE_KEY));
}
