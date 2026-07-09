import posthog from "posthog-js";

const POSTHOG_KEY = import.meta.env.VITE_POSTHOG_KEY as string | undefined;
const POSTHOG_HOST = (import.meta.env.VITE_POSTHOG_HOST as string | undefined) ?? "https://us.i.posthog.com";

export function initAnalytics(): void {
  if (!POSTHOG_KEY) {
    return;
  }

  posthog.init(POSTHOG_KEY, {
    api_host: POSTHOG_HOST,
    capture_pageview: false,
    autocapture: false,
    persistence: "memory",
  });
}

export function identifyClientUser(userId: string, properties: Record<string, string | number | boolean | null>): void {
  if (!POSTHOG_KEY) {
    return;
  }

  posthog.identify(userId, properties);
}

export function trackEvent(eventName: string, properties?: Record<string, string | number | boolean | null>): void {
  if (!POSTHOG_KEY) {
    return;
  }

  posthog.capture(eventName, properties);
}

export function resetAnalytics(): void {
  if (!POSTHOG_KEY) {
    return;
  }

  posthog.reset();
}
