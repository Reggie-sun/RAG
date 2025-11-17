import type { ReactNode } from "react";
import { cn } from "../../lib/utils";

interface CardProps {
  title?: ReactNode;
  extra?: ReactNode;
  children: ReactNode;
  className?: string;
  contentClassName?: string;
  "aria-live"?: "polite" | "assertive" | "off";
  "aria-busy"?: boolean;
}

export function Card({
  title,
  extra,
  children,
  className,
  contentClassName,
  ...ariaProps
}: CardProps) {
  return (
    <section
      className={cn(
        "rounded-3xl border border-white/30 bg-gradient-to-br from-white/92 via-white/70 to-white/30 shadow-[0_20px_45px_rgba(103,119,239,0.25)] backdrop-blur-xl text-[#2b174d]",
        "dark:from-slate-900/80 dark:via-slate-900/50 dark:to-slate-900/20 dark:border-white/10 dark:text-slate-100",
        className,
      )}
      {...ariaProps}
    >
      {(title || extra) && (
        <header className="flex items-center justify-between px-4 py-3 border-b border-white/20 dark:border-white/5">
          <h3 className="text-sm font-semibold gradient-text">
            {title}
          </h3>
          {extra && <div className="shrink-0">{extra}</div>}
        </header>
      )}
      <div className={cn("p-4", contentClassName)}>{children}</div>
    </section>
  );
}
