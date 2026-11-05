import { z } from "zod";
export const adminSearch = z.object({
  job_type: z.enum(["transcription", "notes"]).optional().catch(undefined),
  status: z.enum(["queued", "running", "succeeded", "failed"]).optional().catch(undefined),
});
