import { HttpResponse, http } from "msw";
import type { Schemas } from "@/shared/api/types";
import { page } from "@/shared/testing/fixtures";
import { server } from "@/shared/testing/server";

export const STAMP = "2026-11-05T10:00:00Z";
export function job(changes: Partial<Schemas["JobSnapshot"]> = {}): Schemas["JobSnapshot"] {
  return {
    job_id: "job-1",
    workspace_id: "workspace-alpha",
    job_type: "transcription",
    status: "queued",
    created_at: STAMP,
    queued_at: null,
    started_at: null,
    finished_at: null,
    attempts_started: 0,
    as_of: STAMP,
    queue_wait_seconds: null,
    running_seconds: null,
    last_queue_wait_seconds: null,
    last_attempt_duration_seconds: null,
    total_elapsed_seconds: 10,
    failure_code: null,
    failure_description: null,
    timing_anomaly: false,
    ...changes,
  };
}
export const metrics: Schemas["MetricsRead"] = {
  status: "ok",
  generated_at: STAMP,
  jobs: [
    {
      job_type: "transcription",
      queued: 1,
      running: 0,
      failed: 0,
      unpublished: 1,
      oldest_queue_wait_seconds: null,
      unknown_queue_waits: 1,
    },
  ],
};
export function serve() {
  server.use(
    http.get("/api/v1/admin/metrics", () => HttpResponse.json(metrics)),
    http.get("/api/v1/admin/jobs", () => HttpResponse.json(page([job()]))),
  );
}
