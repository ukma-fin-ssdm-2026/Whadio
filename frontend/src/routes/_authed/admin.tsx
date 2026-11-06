import { useQueryClient } from "@tanstack/react-query";
import { createFileRoute, useRouter } from "@tanstack/react-router";
import { useCallback } from "react";
import { sessionQueries } from "@/features/accounts/api/session";
import { AdminPage } from "@/features/admin/AdminPage";
import { adminSearch } from "@/features/admin/search";
export const Route = createFileRoute("/_authed/admin")({
  validateSearch: adminSearch,
  component: AdminRoute,
});
function AdminRoute() {
  const client = useQueryClient();
  const router = useRouter();
  const onForbidden = useCallback(() => {
    void client.invalidateQueries({ queryKey: sessionQueries.me().queryKey });
  }, [client]);
  const filters = Route.useSearch();
  const navigate = Route.useNavigate();
  return (
    <AdminPage
      onForbidden={onForbidden}
      filters={filters}
      workspaceHref={(workspace_id) =>
        router.buildLocation({ to: "/admin", search: { ...filters, workspace_id } }).href
      }
      onFilters={(search) => navigate({ search, resetScroll: false })}
    />
  );
}
