import { formatDuration } from "@/shared/lib/format-duration";

export const duration = (value: number | null) =>
  value === null ? "Unknown" : formatDuration(Math.floor(value));
export const timestamp = (value: string) => new Date(value).toLocaleString();
export const title = (value: string) => value.charAt(0).toUpperCase() + value.slice(1);
