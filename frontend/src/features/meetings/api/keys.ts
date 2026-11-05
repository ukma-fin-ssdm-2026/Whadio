export const workspaceListsKey = (workspaceId: string) =>
  ["meetings", "list", workspaceId] as const;
export const detailKey = (meetingId: string) => ["meetings", "detail", meetingId] as const;
export const foldersKey = (workspaceId: string) => ["folders", workspaceId] as const;
