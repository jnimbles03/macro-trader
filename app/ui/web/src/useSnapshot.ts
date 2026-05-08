import { useEffect, useState } from "react";
import type { SnapshotPayload } from "./types";

const REFRESH_MS = 30_000;

// Module-level cache so Insights + MarketsPanel share one fetch.
let cached: SnapshotPayload | null = null;
let inFlight: Promise<SnapshotPayload | null> | null = null;
const subscribers = new Set<(s: SnapshotPayload | null) => void>();

const fetchSnapshot = async (): Promise<SnapshotPayload | null> => {
  if (inFlight) return inFlight;
  inFlight = (async () => {
    try {
      const res = await fetch("/api/snapshot");
      const json: SnapshotPayload = await res.json();
      cached = json;
      subscribers.forEach((fn) => fn(json));
      return json;
    } catch {
      return cached;
    } finally {
      inFlight = null;
    }
  })();
  return inFlight;
};

let timer: ReturnType<typeof setInterval> | null = null;
const ensurePolling = () => {
  if (timer) return;
  fetchSnapshot();
  timer = setInterval(fetchSnapshot, REFRESH_MS);
};

export function useSnapshot(): SnapshotPayload | null {
  const [snap, setSnap] = useState<SnapshotPayload | null>(cached);
  useEffect(() => {
    subscribers.add(setSnap);
    ensurePolling();
    return () => {
      subscribers.delete(setSnap);
    };
  }, []);
  return snap;
}
