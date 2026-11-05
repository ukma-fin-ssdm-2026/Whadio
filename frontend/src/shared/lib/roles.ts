import type { Schemas } from "../api/types";

export const canManage = (role: Schemas["Role"]) => role === "moderator" || role === "owner";
