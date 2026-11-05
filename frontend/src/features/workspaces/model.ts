import type { Schemas } from "@/shared/api/types";

export const PRESETS: Schemas["Preset"][] = ["summary", "detailed", "interview"];

export interface Workspace {
  id: string;
  name: string;
  role: Schemas["Role"];
  members: number;
}

export function mapWorkspace(item: Schemas["WorkspaceSummary"]): Workspace {
  return {
    id: item.id,
    name: item.name,
    role: item.my_role,
    members: item.member_count,
  };
}
