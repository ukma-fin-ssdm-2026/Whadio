export function formatDuration(seconds) {
  if (seconds == null) return "Duration pending";

  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainingSeconds = seconds % 60;

  if (hours > 0) {
    const minutePart = minutes > 0 ? ` ${minutes}m` : "";
    return `${hours}h${minutePart} ${remainingSeconds}s`;
  }

  return `${minutes}m ${remainingSeconds}s`;
}