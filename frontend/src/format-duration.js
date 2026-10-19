export function formatDuration(seconds) {
  if (seconds == null) return "Duration pending";

  const minutes = Math.floor(seconds / 60);
  const remaining = seconds % 60;

  return `${minutes}m ${remaining}s`;
}