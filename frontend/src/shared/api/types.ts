import type { components } from "./schema.gen";

export type Schemas = components["schemas"];

export type WorkspaceUpdate = Schemas["WorkspaceUpdate"];
export type MeetingPage = Schemas["Page_MeetingSummary_"];
export type MeetingRead = Schemas["MeetingRead"];
export type TranscriptRead = Schemas["TranscriptRead"];
export type NotePage = Schemas["Page_NoteRead_"];
export type PlaybackLink = Schemas["PlaybackLink"];
