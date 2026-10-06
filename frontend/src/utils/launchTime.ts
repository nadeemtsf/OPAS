/** UTC values for the launch-time field, whose label explicitly says UTC. */
export function utcLaunchTimeValue(iso: string): string {
  return new Date(iso).toISOString().slice(0, -1);
}

/** Retain the exact checked timestamp, including sub-millisecond precision. */
export function launchTimeForRequest(value: string, checkedIso: string | null): string {
  if (checkedIso && value === utcLaunchTimeValue(checkedIso)) {
    return checkedIso;
  }
  // datetime-local has no zone; this field represents UTC in every browser zone.
  return new Date(`${value}Z`).toISOString();
}
