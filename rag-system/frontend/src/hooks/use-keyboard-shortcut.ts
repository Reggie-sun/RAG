import { useEffect } from "react";

type ShortcutHandler = (event: KeyboardEvent) => void;

export function useKeyboardShortcut(
  key: string,
  handler: ShortcutHandler,
  options?: { meta?: boolean; ctrl?: boolean },
) {
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const matchesKey = event.key.toLowerCase() === key.toLowerCase();
      const requiresMeta = options?.meta ?? false;
      const requiresCtrl = options?.ctrl ?? false;

      if (!matchesKey) return;
      if (requiresMeta && !event.metaKey) return;
      if (requiresCtrl && !event.ctrlKey) return;

      handler(event);
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [handler, key, options?.ctrl, options?.meta]);
}
