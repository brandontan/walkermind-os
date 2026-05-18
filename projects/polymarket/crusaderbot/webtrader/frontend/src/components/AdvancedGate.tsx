import type { ReactNode } from "react";
import { useUiMode } from "../lib/uiMode";

export function AdvancedOnly({ children }: { children: ReactNode }) {
  const { advanced } = useUiMode();
  if (!advanced) return null;
  return <>{children}</>;
}

export function EssentialOnly({ children }: { children: ReactNode }) {
  const { advanced } = useUiMode();
  if (advanced) return null;
  return <>{children}</>;
}
