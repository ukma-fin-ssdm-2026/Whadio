import { apiClient } from "@/shared/api/client";
import type { Schemas } from "@/shared/api/types";
import { expectNoContent, unwrap } from "@/shared/api/unwrap";

// Completion bodies contain secrets, so they must not become cached Query mutation variables.
export function completeRegistration(id: string, body: Schemas["RegistrationComplete"]) {
  return unwrap(
    apiClient.POST("/api/v1/registrations/{registration_id}/complete", {
      params: { path: { registration_id: id } },
      body,
    }),
  );
}

export function completePasswordReset(id: string, body: Schemas["PasswordResetComplete"]) {
  return expectNoContent(
    apiClient.POST("/api/v1/password-resets/{reset_id}/complete", {
      params: { path: { reset_id: id } },
      body,
    }),
  );
}

export function linkToken(hash: string): string | null {
  const values = new URLSearchParams(hash.replace(/^#/, "")).getAll("token");
  return values.length === 1 && values[0] ? values[0] : null;
}
