export interface RecordedRange {
  recordedFrom?: string;
  recordedTo?: string;
}

export const RANGE_ORDER_MESSAGE = "End date is before the start date";

export function recordedRange(from: string, to: string): RecordedRange | "unordered" {
  if (from && to && to < from) return "unordered";
  const end = new Date(`${to}T00:00`);
  end.setDate(end.getDate() + 1);
  return {
    recordedFrom: from ? new Date(`${from}T00:00`).toISOString() : undefined,
    recordedTo: to ? end.toISOString() : undefined,
  };
}
