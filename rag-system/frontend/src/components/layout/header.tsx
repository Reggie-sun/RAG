import { ThemeToggle } from "./theme-toggle";
import { cn } from "../../lib/utils";

interface AppHeaderProps {
  sidebarHidden: boolean;
  onToggleSidebar: () => void;
}

export function AppHeader({ sidebarHidden, onToggleSidebar }: AppHeaderProps) {
  const sharedButtonClass = cn(
    "w-full max-w-[240px] sm:max-w-[260px]",
    sidebarHidden ? "md:max-w-[260px]" : "md:max-w-[240px]",
  );

  return (
    <header
      className={cn(
        "flex flex-col gap-4 transition-all",
        sidebarHidden
          ? "items-center text-center md:flex-col"
          : "md:flex-row md:items-center md:justify-between",
      )}
    >
      <div
        className={cn(
          "space-y-3",
          sidebarHidden ? "max-w-3xl" : "max-w-2xl",
        )}
      >
        <p className="text-sm uppercase tracking-[0.3em] text-white text-ensure-contrast font-medium">
          内部知识助手
        </p>
        <h1
          className={cn(
            "gradient-text mb-2 transition-all",
            sidebarHidden ? "text-4xl md:text-5xl" : "text-3xl md:text-4xl",
          )}
        >
          Document RAG Search
        </h1>
        <p
          className={cn(
            "text-white/90 text-ensure-contrast leading-relaxed transition-all",
            sidebarHidden ? "text-lg" : "text-base",
          )}
        >
          上传资料、查询知识库，快速获得带引用的答案。支持文档抽取与通用知识，
          始终了解结果来自何处。
        </p>
      </div>
      <div
        className={cn(
          "flex w-full flex-col items-center gap-5 transition-all",
          !sidebarHidden && "md:items-end"
        )}
      >
        <ThemeToggle className={sharedButtonClass} />
        <button
          type="button"
          onClick={onToggleSidebar}
          aria-pressed={!sidebarHidden}
          className={cn(
            "gradient-button inline-flex items-center justify-center rounded-full px-4 py-2 text-xs font-semibold uppercase tracking-wide transition-all hover:scale-105 active:scale-95",
            sharedButtonClass,
          )}
        >
          {sidebarHidden ? "显示侧栏" : "隐藏侧栏"}
        </button>
      </div>
    </header>
  );
}
