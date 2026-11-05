import { z } from "zod";
import type { Schemas } from "@/shared/api/types";

export const JOB_TYPES = [
  "transcription",
  "notes",
] as const satisfies readonly Schemas["JobType"][];
export const JOB_STATUSES = [
  "queued",
  "running",
  "succeeded",
  "failed",
] as const satisfies readonly Schemas["JobStatus"][];

export const adminSearch = z.object({
  job_type: z.enum(JOB_TYPES).optional().catch(undefined),
  status: z.enum(JOB_STATUSES).optional().catch(undefined),
});
