import type { ButtonHTMLAttributes, ReactNode } from "react";
import { cn } from "../../lib/utils";

interface TagProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  children: ReactNode;
  active?: boolean;
  asSpan?: boolean;
}

export function Tag({ children, active, className, disabled, asSpan = false, ...props }: TagProps) {
  const TagComponent = asSpan ? "span" : "button";

  return (
    <TagComponent
      {...(asSpan ? {} : { type: "button" })}
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-semibold transition-all",
        "text-[#3a2154] bg-white/70 border-white/70 hover:text-[#20112f] hover:bg-white",
        "dark:text-slate-100 dark:bg-white/10 dark:border-white/20",
        active &&
          "gradient-button border-none shadow-[0_8px_20px_rgba(102,126,234,0.4)] text-white hover:scale-105",
        disabled && "opacity-50 pointer-events-none",
        !asSpan && "cursor-pointer",
        className,
      )}
      role={asSpan ? undefined : "button"}
      tabIndex={asSpan ? undefined : 0}
      aria-pressed={asSpan ? undefined : active}
      data-active={active}
      disabled={asSpan ? undefined : disabled}
      {...props}
    >
      {children}
    </TagComponent>
  );
}
