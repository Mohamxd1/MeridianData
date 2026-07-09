import { ReactNode, useEffect } from "react";
import { initAnalytics } from "./posthog";

type AnalyticsProviderProps = {
  children: ReactNode;
};

export function AnalyticsProvider({ children }: AnalyticsProviderProps) {
  useEffect(() => {
    initAnalytics();
  }, []);

  return <>{children}</>;
}
