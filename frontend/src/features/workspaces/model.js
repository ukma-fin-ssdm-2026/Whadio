import { titleCase } from "@/shared/lib/format";

export function mapWorkspace(item, details = {}) {
  return {
    id: item.id,
    name: item.name,
    role: titleCase(item.my_role),
    members: item.member_count,
    provider: titleCase(item.notes_provider),
    preset: details.default_preset ?? item.default_preset ?? "summary",
  };
}
