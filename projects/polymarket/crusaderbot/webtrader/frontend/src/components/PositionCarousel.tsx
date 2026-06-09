import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

type Props = {
  /** One slide per child. With <= 1 child the carousel renders the child as-is. */
  children: ReactNode[];
};

/**
 * Horizontal, swipe-native carousel for open-position cards — one card per view.
 *
 * Built on CSS scroll-snap: users swipe on touch (with native momentum) or use
 * the dots on desktop, and the view always rests cleanly on a card. There is no
 * passive auto-advance, so the layout can never be caught mid-transition (the
 * old translateX auto-slider showed two half-cards while animating, which read
 * as broken on mobile). Responsive by construction — the track is the viewport
 * width and every slide snaps to full width on any screen size.
 */
export function PositionCarousel({ children }: Props) {
  const slides = children;
  const count = slides.length;
  const trackRef = useRef<HTMLDivElement>(null);
  const [index, setIndex] = useState(0);

  // Derive the active slide from the scroll position so the dots stay in sync
  // with native swipe / momentum scrolling.
  const onScroll = useCallback(() => {
    const el = trackRef.current;
    if (!el) return;
    const w = el.clientWidth || 1;
    const i = Math.min(Math.max(Math.round(el.scrollLeft / w), 0), count - 1);
    setIndex((prev) => (prev === i ? prev : i));
  }, [count]);

  const goTo = useCallback((i: number) => {
    const el = trackRef.current;
    if (!el) return;
    el.scrollTo({ left: i * el.clientWidth, behavior: "smooth" });
  }, []);

  // Keep the active index valid AND the scroll position synced when the slide
  // count shrinks (a position closed) — otherwise the track stays scrolled to a
  // now-missing slide while the dots point elsewhere.
  useEffect(() => {
    if (index > count - 1) {
      const next = Math.max(0, count - 1);
      setIndex(next);
      const el = trackRef.current;
      if (el) el.scrollTo({ left: next * el.clientWidth });
    }
  }, [count, index]);

  if (count <= 1) return <>{slides}</>;

  return (
    <div>
      <div
        ref={trackRef}
        onScroll={onScroll}
        className="flex items-start overflow-x-auto snap-x snap-mandatory no-scrollbar scroll-smooth"
      >
        {slides.map((slide, i) => (
          <div key={i} className="min-w-full shrink-0 snap-center px-0.5">
            {slide}
          </div>
        ))}
      </div>
      <div className="flex items-center justify-center gap-1.5 mt-1.5">
        {slides.map((_, i) => (
          <button
            key={i}
            type="button"
            aria-label={`Go to position ${i + 1}`}
            aria-current={i === index}
            onClick={() => goTo(i)}
            className="h-1.5 rounded-full transition-all"
            style={{
              width: i === index ? "14px" : "6px",
              background: i === index ? "var(--gold, #F5C842)" : "var(--ink-4, #2A3550)",
            }}
          />
        ))}
      </div>
    </div>
  );
}
