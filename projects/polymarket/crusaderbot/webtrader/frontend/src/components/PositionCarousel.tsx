import { useEffect, useRef, useState, type ReactNode } from "react";

type Props = {
  /** One slide per child. With <= 1 child the carousel renders the child as-is. */
  children: ReactNode[];
  /** Auto-advance interval in ms. */
  intervalMs?: number;
};

/**
 * Horizontal auto-advancing carousel for open-position cards. Shows one slide
 * at a time so a long position list stays compact on the Home view. Auto-play
 * pauses while the user is interacting (pointer down / hover) and resumes after.
 */
export function PositionCarousel({ children, intervalMs = 5000 }: Props) {
  const slides = children;
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false);
  const count = slides.length;

  // Keep the active index valid when the slide count shrinks (position closed).
  useEffect(() => {
    if (index > count - 1) setIndex(Math.max(0, count - 1));
  }, [count, index]);

  const pausedRef = useRef(paused);
  pausedRef.current = paused;

  useEffect(() => {
    if (count <= 1) return;
    const id = setInterval(() => {
      if (!pausedRef.current) setIndex((i) => (i + 1) % count);
    }, intervalMs);
    return () => clearInterval(id);
  }, [count, intervalMs]);

  if (count <= 1) return <>{slides}</>;

  return (
    <div
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onPointerDown={() => setPaused(true)}
      onPointerUp={() => setPaused(false)}
    >
      <div className="overflow-hidden">
        <div
          className="flex transition-transform duration-500 ease-out"
          style={{ transform: `translateX(-${index * 100}%)` }}
        >
          {slides.map((slide, i) => (
            <div key={i} className="min-w-full shrink-0 px-0.5">
              {slide}
            </div>
          ))}
        </div>
      </div>
      <div className="flex items-center justify-center gap-1.5 mt-1.5">
        {slides.map((_, i) => (
          <button
            key={i}
            type="button"
            aria-label={`Go to position ${i + 1}`}
            onClick={() => setIndex(i)}
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
