import type { ReactNode } from "react";
import { AdvancedOnly, EssentialOnly } from "./AdvancedGate";

type Props = {
  essential: ReactNode;
  advanced: ReactNode;
};

/**
 * Renders one of two stat layouts based on Advanced Mode.
 *  - Essential: 2 cards, even split (Balance + Open).
 *  - Advanced:  asymmetric 1.3fr/1fr with a row-spanning Balance card.
 */
export function StatsGrid({ essential, advanced }: Props) {
  return (
    <>
      <EssentialOnly>
        <div className="grid grid-cols-[1fr_1fr] gap-2 mb-3">{essential}</div>
      </EssentialOnly>
      <AdvancedOnly>
        <div className="grid grid-cols-[1.3fr_1fr] gap-2 mb-3">{advanced}</div>
      </AdvancedOnly>
    </>
  );
}
