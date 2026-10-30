import type { Schemas } from "@/shared/api/types";
import { titleCase } from "@/shared/lib/format";

export interface Workspace {
  id: string;
  name: string;
  role: string;
  members: number;
}

export function mapWorkspace(item: Schemas["WorkspaceSummary"]): Workspace {
  return {
    id: item.id,
    name: item.name,
    role: titleCase(item.my_role),
    members: item.member_count,
  };
}
