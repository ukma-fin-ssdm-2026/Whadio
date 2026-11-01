import { createFileRoute } from "@tanstack/react-router";
import { Breadcrumbs } from "@/app/layout/Breadcrumbs";
import { McpKeyPanel } from "@/features/accounts/components/McpKeyPanel";
import { PageHeader } from "@/shared/ui/PageHeader";

export const Route = createFileRoute("/_authed/settings/assistant")({
  component: AssistantSettingsRoute,
});

function AssistantSettingsRoute() {
  return (
    <>
      <Breadcrumbs current="AI assistant" />
      <PageHeader title="AI assistant" />
      <McpKeyPanel />
    </>
  );
}
