import {
  forwardRef,
  useMemo,
  type FormEvent,
  type KeyboardEvent,
  type MutableRefObject,
} from "react";
import { Search } from "lucide-react";
import { Card } from "../common/card";
import { Tag } from "../common/tag";
import { cn } from "../../lib/utils";

interface SearchFormProps {
  query: string;
  onQueryChange: (value: string) => void;
  onSubmit: (query: string) => void;
  onClear: () => void;
  isSearching: boolean;
  inputRef?: MutableRefObject<HTMLInputElement | null>;
  placeholder?: string;
  suggestions?: string[];
  onSuggestionClick?: (value: string) => void;
  options: SearchOptionState;
  onOptionsChange: (next: SearchOptionState) => void;
  focusMode?: boolean;
}

export interface SearchOptionState {
  docOnly: boolean;
  allowWeb: boolean;
  rerank: boolean;
  topK: number;
}

export const SearchForm = forwardRef<HTMLInputElement, SearchFormProps>(
  (
    {
      query,
      onQueryChange,
      onSubmit,
      onClear,
      isSearching,
      inputRef,
      placeholder,
      suggestions,
      onSuggestionClick,
      options,
      onOptionsChange,
      focusMode = false,
    },
    ref,
  ) => {
    const hintText = useMemo(
      () =>
        "限定问题范围，例如：根据文档回答｜允许联网（需说明来源）｜TopK 10｜Rerank 开启",
      [],
    );

    function handleSubmit(event: FormEvent<HTMLFormElement>) {
      event.preventDefault();
      if (!query.trim()) return;
      onSubmit(query.trim());
    }

    function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
      if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        onSubmit(query.trim());
      }
    }

    const optionTagClass = focusMode ? "text-sm px-3 py-1.5" : undefined;
    const suggestionTagClass = focusMode ? "text-base px-3.5 py-1.5" : "text-sm";
    const safeTopK = useMemo(
      () => Math.min(Math.max(options.topK ?? 3, 3), 10),
      [options.topK],
    );

    return (
      <Card title="搜索" aria-label="搜索卡片">
        <form
          className={cn("space-y-3", focusMode && "space-y-4")}
          onSubmit={handleSubmit}
        >
          <div className="relative">
            <div className="pointer-events-none absolute left-4 top-1/2 hidden -translate-y-1/2 text-slate-400 sm:block">
              <Search className="h-4 w-4" aria-hidden="true" />
            </div>
            <input
              ref={(node) => {
                if (typeof ref === "function") {
                  ref(node);
                } else if (ref) {
                  (ref as MutableRefObject<HTMLInputElement | null>).current =
                    node;
                }
                if (inputRef) {
                  inputRef.current = node;
                }
              }}
              value={query}
              onChange={(event) => onQueryChange(event.target.value)}
              onKeyDown={handleKeyDown}
              type="search"
              placeholder={
                placeholder ??
                "解释一下 CPPS，说一下常见的 Linux 命令、git 命令"
              }
              aria-label="输入搜索问题"
              className={cn(
                "w-full rounded-2xl border border-white/60 bg-white/90 px-4 py-3 text-base text-[#2b174d]",
                "placeholder:text-[#806296] focus:outline-none focus:ring-2 focus:ring-[#a26bde]/40",
                "dark:bg-slate-900/60 dark:border-white/10 dark:text-white dark:placeholder:text-slate-400",
                "sm:pl-11 pr-36",
                focusMode && "text-lg md:text-xl py-4 sm:pl-12 pr-40"
              )}
              autoComplete="off"
            />
            <div className="absolute right-1.5 top-1.5 flex gap-2">
              <button
                type="button"
                className={cn(
                  "rounded-full border border-[#d6c1f5] bg-white/80 px-3 py-2 text-sm font-semibold text-[#5c2e78] transition hover:bg-white",
                  focusMode && "px-4 py-2.5 text-base"
                )}
                onClick={onClear}
                disabled={!query && !isSearching}
              >
                清空
              </button>
              <button
                type="submit"
                className={cn(
                  "gradient-button rounded-full px-5 py-2 text-sm font-semibold shadow-lg shadow-[#7f5bff]/30",
                  focusMode && "px-6 py-2.5 text-base"
                )}
                disabled={!query.trim() || isSearching}
              >
                {isSearching ? "检索中…" : "搜索"}
              </button>
            </div>
          </div>

          <p
            className={cn(
              "text-xs font-medium text-[#51336f]",
              focusMode && "text-sm leading-relaxed"
            )}
          >
            {hintText}
          </p>

          <div className="flex flex-wrap gap-2">
            <Tag
              onClick={() =>
                onOptionsChange({ ...options, docOnly: !options.docOnly })
              }
              active={options.docOnly}
              className={optionTagClass}
            >
              仅文档回答
            </Tag>
            <Tag
              onClick={() =>
                onOptionsChange({ ...options, allowWeb: !options.allowWeb })
              }
              active={options.allowWeb}
              className={optionTagClass}
            >
              允许联网
            </Tag>
            <Tag
              onClick={() =>
                onOptionsChange({ ...options, rerank: !options.rerank })
              }
              active={options.rerank}
              className={optionTagClass}
            >
              Rerank: {options.rerank ? "On" : "Off"}
            </Tag>
          </div>

          <div className="flex w-full flex-col gap-1">
            <div className="flex items-center justify-between text-xs font-semibold text-[#51336f]">
              <span>TopK: {safeTopK}</span>
              <span className="text-[11px] font-medium text-[#806296]">3 - 10</span>
            </div>
            <div className="rounded-full bg-gradient-to-r from-[#f6efff] via-[#dec3ff] to-[#b28bff] px-4 py-3 shadow-inner shadow-[#b28bff]/40">
              <input
                type="range"
                min={3}
                max={10}
                step={1}
                value={safeTopK}
                onChange={(event) => {
                  const nextValue = Number(event.target.value) || 3;
                  onOptionsChange({ ...options, topK: nextValue });
                }}
                className="w-full bg-transparent accent-[#8f65e7]"
              />
            </div>
          </div>

          {Boolean(suggestions?.length) && (
            <div className="flex flex-wrap gap-2">
              {suggestions?.slice(0, 5).map((item) => (
                <Tag
                  key={item}
                  onClick={() => onSuggestionClick?.(item)}
                  disabled={isSearching}
                  className={cn("text-sm", suggestionTagClass)}
                >
                  {item}
                </Tag>
              ))}
            </div>
          )}
        </form>
      </Card>
    );
  },
);
SearchForm.displayName = "SearchForm";
