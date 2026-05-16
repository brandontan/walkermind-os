type Props = {
  checked: boolean;
  onChange: (next: boolean) => void;
  ariaLabel?: string;
  disabled?: boolean;
};

export function Toggle({ checked, onChange, ariaLabel, disabled = false }: Props) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={ariaLabel}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative w-11 h-6 rounded-[13px] flex-shrink-0 transition-all border ${
        disabled ? "opacity-40 cursor-not-allowed" : "cursor-pointer"
      } ${
        checked
          ? "border-gold"
          : "border-border-2"
      }`}
      style={{
        background: checked ? "rgba(245,200,66,0.15)" : "var(--surface-3,#1A2540)",
      }}
    >
      <span
        aria-hidden
        className="absolute top-0.5 w-[18px] h-[18px] rounded-full transition-all"
        style={{
          left: checked ? "22px" : "2px",
          background: checked ? "var(--gold,#F5C842)" : "var(--ink-3,#455370)",
          boxShadow: checked ? "0 0 10px var(--gold,#F5C842)" : "none",
          transitionTimingFunction: "cubic-bezier(0.4,0,0.2,1)",
          transitionDuration: "0.25s",
        }}
      />
    </button>
  );
}
