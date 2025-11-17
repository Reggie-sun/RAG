import { Moon, Sun } from "lucide-react";
import { Button } from "../ui/button";
import { useTheme } from "../../providers/theme-provider";
import { cn } from "../../lib/utils";

interface ThemeToggleProps {
  className?: string;
}

export function ThemeToggle({ className }: ThemeToggleProps) {
  const { theme, toggleTheme } = useTheme();
  const isDark = theme === "dark";

  return (
    <Button
      variant="default"
      type="button"
      aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
      onClick={toggleTheme}
      className={cn(
        "gradient-button inline-flex items-center justify-center gap-2 rounded-full px-4 py-2 text-xs font-semibold uppercase tracking-wide text-white transition-all hover:scale-105 active:scale-95",
        className,
      )}
    >
      {isDark ? (
        <>
          <Sun className="h-4 w-4" aria-hidden="true" />
          <span>亮色模式</span>
        </>
      ) : (
        <>
          <Moon className="h-4 w-4" aria-hidden="true" />
          <span>暗色模式</span>
        </>
      )}
    </Button>
  );
}
