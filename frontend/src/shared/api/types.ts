import type { components } from "./schema.gen";

export type Schemas = components["schemas"];

export type SessionRead = Schemas["SessionRead"];
export type WorkspacePage = Schemas["Page_WorkspaceSummary_"];
export type WorkspaceRead = Schemas["WorkspaceRead"];
export type WorkspaceUpdate = Schemas["WorkspaceUpdate"];
export type MeetingPage = Schemas["Page_MeetingSummary_"];
export type MeetingRead = Schemas["MeetingRead"];
export type TranscriptRead = Schemas["TranscriptRead"];
export type NotePage = Schemas["Page_NoteRead_"];
export type PlaybackLink = Schemas["PlaybackLink"];
export type McpKeyPage = Schemas["Page_McpKeyRead_"];
export type McpKeyCreated = Schemas["McpKeyCreated"];
