export function formatDuration(seconds) {
  if (seconds == null) return "Duration pending";

  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainingSeconds = seconds % 60;

  if (hours > 0) {
    const parts = [`${hours}h`];

    if (minutes > 0) {
      parts.push(`${minutes}m`);
    }

    if (remainingSeconds > 0) {
      parts.push(`${remainingSeconds}s`);
    }

    return parts.join(" ");
  }

  return `${minutes}m ${remainingSeconds}s`;
}