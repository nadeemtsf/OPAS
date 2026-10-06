import type { WindowDiagnostics, WindowSearchResponse } from "../types";

export function validateWindowResponse(value: unknown): WindowSearchResponse {
  const result = value as WindowSearchResponse;
  const d = result?.diagnostics;
  const counts = [d?.checked_launch_samples, d?.clear_launch_samples,
    d?.obstructed_launch_samples, d?.returned_windows];
  if (!Array.isArray(result?.windows) || d?.status !== "complete" ||
      d.returned_windows !== result.windows.length || result.windows.length > 5 ||
      !Number.isFinite(d.verification_step_seconds) || d.verification_step_seconds! <= 0 ||
      d.verification_step_seconds! > 10 ||
      counts.some(count => !Number.isInteger(count) || count! < 0) ||
      d.checked_launch_samples !== (d.clear_launch_samples ?? -1) + (d.obstructed_launch_samples ?? -1)) {
    throw new Error("The server did not return complete window verification. Check the request log.");
  }
  for (const window of result.windows) {
    const v = window.verification;
    const start = Date.parse(window.start), end = Date.parse(window.end);
    if (!v || v.status !== "passed" || !v.endpoints_checked || !v.horizon_checked ||
        !v.duration_checked || !v.coverage_checked || v.unsafe_launches !== 0 ||
        !Number.isFinite(start) || !Number.isFinite(end) || start >= end ||
        !Number.isFinite(v.duration_seconds) || v.duration_seconds < 900 ||
        Math.abs((end-start)/1000-v.duration_seconds) > 0.002 ||
        !Number.isFinite(window.duration_minutes) ||
        Math.abs(window.duration_minutes-v.duration_seconds/60) > 0.0051 ||
        !Number.isInteger(v.checked_launches) ||
        v.checked_launches < Math.ceil(v.duration_seconds/d.verification_step_seconds!) + 1 ||
        !Number.isFinite(v.max_launch_gap_seconds) || v.max_launch_gap_seconds <= 0 ||
        v.max_launch_gap_seconds > d.verification_step_seconds! ||
        !Number.isFinite(Date.parse(d.search_start_utc ?? "")) ||
        !Number.isFinite(Date.parse(d.search_end_utc ?? "")) ||
        start < Date.parse(d.search_start_utc!) || end > Date.parse(d.search_end_utc!)) {
      throw new Error("A returned window failed the client coverage checks. It cannot be selected.");
    }
  }
  return result;
}

export async function readWindowStream(
  response: Response,
  onProgress: (progress: WindowDiagnostics) => void,
): Promise<WindowSearchResponse> {
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === "string" ? body.detail : `Search request failed (HTTP ${response.status}).`);
  }
  if (!response.body || !response.headers.get("content-type")?.includes("text/event-stream")) {
    throw new Error("The server did not open a progress stream. Update the backend and retry.");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffered = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffered += decoder.decode(value, { stream: !done });
      let boundary;
      while ((boundary = buffered.search(/\r?\n\r?\n/)) >= 0) {
        const separator = buffered.slice(boundary).match(/^\r?\n\r?\n/)![0];
        const frame = buffered.slice(0, boundary);
        buffered = buffered.slice(boundary+separator.length);
        const lines = frame.split(/\r?\n/);
        const event = lines.find(line => line.startsWith("event:"))?.slice(6).trim();
        const text = lines.filter(line => line.startsWith("data:")).map(line => line.slice(5).trimStart()).join("\n");
        if (!text) continue; // Heartbeats are comments, not successful results.
        const data = JSON.parse(text);
        if (event === "progress") onProgress(data);
        else if (event === "error") throw new Error(data.detail ?? "Window verification was incomplete.");
        else if (event === "result") return validateWindowResponse(data);
      }
      if (done) throw new Error("The progress stream ended before verification completed. No windows were accepted.");
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
