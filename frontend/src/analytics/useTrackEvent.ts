import { useCallback } from "react";
import { trackEvent } from "./posthog";

export function useTrackEvent() {
  return useCallback(
    (eventName: string, properties?: Record<string, string | number | boolean | null>) => {
      trackEvent(eventName, properties);
    },
    [],
  );
}
