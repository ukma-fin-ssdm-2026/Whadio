export function formatDuration(seconds) {
  if (seconds == null) return "Duration pending";

  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remaining = seconds % 60;

  if (hours > 0) {
    return `${hours}h ${minutes}m ${remaining}s`;
  }

  return `${minutes}m ${remaining}s`;
}