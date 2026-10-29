import { screen, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { renderWithProviders } from "@/shared/testing/render";
import { http, server } from "@/shared/testing/server";
import { SignOutButton } from "./SignOutButton";

test.for([
  ["succeeds", 204],
  ["fails", 503],
] as const)("ends the session when the request %s", async ([, status]) => {
  // Arrange
  server.use(
    http.delete("/api/v1/sessions/current", ({ response }) =>
      response.untyped(new Response(null, { status })),
    ),
  );
  const onSignedOut = vi.fn();
  const { user } = renderWithProviders(<SignOutButton onSignedOut={onSignedOut} />);

  // Act
  await user.click(screen.getByRole("button", { name: "Sign out" }));

  // Assert
  await waitFor(() => expect(onSignedOut).toHaveBeenCalledOnce());
});
