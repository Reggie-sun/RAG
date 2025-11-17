import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useKeyboardShortcut } from "./hooks/use-keyboard-shortcut";
import { AppHeader } from "./components/layout/header";
import { SearchForm, type SearchOptionState } from "./components/search/search-form";
import { IndexStatusCard } from "./components/status/index-status-card";
import { EnhancedUploadCard } from "./components/upload/enhanced-upload-card";
import { AnswerPanel } from "./components/answer/answer-panel";
import { FeedbackForm, type FeedbackTagOption } from "./components/answer/feedback-form";
import { askAsync, getTaskResult, searchDocuments, type SearchRequestPayload } from "./services/api";
import type { SearchResponse, TaskResult } from "./types/api";
import { resetSessionId } from "./lib/session";
import { cn } from "./lib/utils";

const ENABLE_QUEUE =
  (import.meta.env.VITE_ENABLE_QUEUE ?? "").toLowerCase() === "true";

const DEFAULT_OPTIONS: SearchOptionState = {
  docOnly: true,
  allowWeb: false,
  rerank: true,
  topK: 6,
};

const DEFAULT_SUGGESTIONS = [
  "总结这篇PDF的核心发现（100字）",
  "提取报告里的行动项并说明责任人",
  "对比两份文档的观点差异",
];

type FeedbackTagId = "missing_citation" | "need_detail" | "missing_risk" | "format_issue";

interface FeedbackTagConfig {
  id: FeedbackTagId;
  label: string;
  text: string;
  description: string;
  autoPredicate?: (result: SearchResponse) => boolean;
}

const FEEDBACK_TAGS: Record<FeedbackTagId, FeedbackTagConfig> = {
  missing_citation: {
    id: "missing_citation",
    label: "引用缺失",
    text: "引用不完整：希望标明具体来源和页码，引用数量至少两条。",
    description: "当前回答引用过少或缺少页码",
    autoPredicate: (result) => (result.citations?.length ?? 0) < 2,
  },
  need_detail: {
    id: "need_detail",
    label: "内容太概括",
    text: "内容太概括：需要列出明确步骤/数量/案例，不要只给结论。",
    description: "回答字数过少或包含“未在文档中找到”",
    autoPredicate: (result) => {
      const answer = (result.answer || "").trim();
      return answer.length < 360 || /未在文档中找到/.test(answer);
    },
  },
  missing_risk: {
    id: "missing_risk",
    label: "风险未覆盖",
    text: "缺少风险与限制：请补充潜在副作用、适用范围或注意事项。",
    description: "风险章节为空或提示未找到",
    autoPredicate: (result) => {
      const answer = result.answer || "";
      return /风险与限制/.test(answer) && /未在文档中找到/.test(answer);
    },
  },
  format_issue: {
    id: "format_issue",
    label: "排版/格式",
    text: "排版问题：请按照模板层级分段、加粗，保证排版统一。",
    description: "标题、缩进或加粗不统一",
  },
};

const FEEDBACK_TAG_LIST = Object.values(FEEDBACK_TAGS);

const deriveAutoFeedbackTags = (res: SearchResponse | null): FeedbackTagId[] => {
  if (!res) {
    return [];
  }
  const tags: FeedbackTagId[] = [];
  for (const tag of FEEDBACK_TAG_LIST) {
    if (tag.autoPredicate && tag.autoPredicate(res)) {
      tags.push(tag.id);
    }
  }
  return tags;
};

export default function App() {
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<SearchResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [hasSearched, setHasSearched] = useState(false);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [suggestions, setSuggestions] = useState<string[]>(DEFAULT_SUGGESTIONS);
  const [isManuallyLoading, setIsManuallyLoading] = useState(false);
  const searchInputRef = useRef<HTMLInputElement | null>(null);
  const pollAttemptsRef = useRef(0);
  const [sidebarHidden, setSidebarHidden] = useState(false);
  const [searchOptions, setSearchOptions] = useState<SearchOptionState>(DEFAULT_OPTIONS);
  const [feedbackDraft, setFeedbackDraft] = useState("");
  const [feedbackTags, setFeedbackTags] = useState<FeedbackTagId[]>([]);

  const autoTagSuggestions = useMemo(() => deriveAutoFeedbackTags(result), [result]);

  const feedbackTagOptions: FeedbackTagOption[] = useMemo(
    () =>
      FEEDBACK_TAG_LIST.map((config) => ({
        id: config.id,
        label: config.label,
        text: config.text,
        description: config.description,
        recommended: autoTagSuggestions.includes(config.id),
      })),
    [autoTagSuggestions],
  );

  useKeyboardShortcut("/", (event) => {
    event.preventDefault();
    searchInputRef.current?.focus();
  });

  // 添加 Ctrl/Cmd+K 快捷键统一检索体验
  useKeyboardShortcut("k", (event) => {
    if (event.ctrlKey || event.metaKey) {
      event.preventDefault();
      searchInputRef.current?.focus();
    }
  });

  const searchMutation = useMutation({
    mutationFn: (payload: SearchRequestPayload) => searchDocuments(payload),
    onSuccess: (data) => {
      setResult(data);
      setError(null);
      setIsManuallyLoading(false);
    },
    onError: (mutationError: unknown) => {
      console.error(mutationError);
      const message =
        mutationError instanceof Error
          ? mutationError.message
          : "搜索失败，请稍后再试。";
      setError(message);
      setIsManuallyLoading(false);
    },
  });

  const askMutation = useMutation({
    mutationFn: (payload: SearchRequestPayload) => askAsync(payload),
    onSuccess: (data) => {
      setError(null);
      if (data.result) {
        setResult(data.result);
        setTaskId(null);
        setIsManuallyLoading(false);
        return;
      }
      setTaskId(data.task_id ?? null);
    },
    onError: (mutationError: unknown) => {
      console.error(mutationError);
      const message =
        mutationError instanceof Error
          ? mutationError.message
          : "正在排队请求失败，请稍后再试。";
      setError(message);
      setIsManuallyLoading(false);
    },
  });

  const taskQuery = useQuery<TaskResult>({
    queryKey: ["ask-result", taskId],
    queryFn: () => getTaskResult(taskId!),
    enabled: Boolean(taskId),
    refetchInterval: (q) => {
      const status = q.state.data?.status?.toLowerCase();
      if (status === "success" || status === "failure") return false;

      // 页面不可见暂停
      if (typeof document !== "undefined" && document.visibilityState !== "visible") {
        return false;
      }

      // 指数退避 + 封顶：2s → 4s → 8s → 10s
      const n = pollAttemptsRef.current++;
      const base = 2000;
      const ms = Math.min(10000, base * Math.pow(2, Math.min(n, 2)));
      return ms;
    },
    refetchOnWindowFocus: true, // 回到前台立即触发一次
  });

  useEffect(() => {
    const data = taskQuery.data;
    if (!data || !taskId) return;

    const status = data.status?.toLowerCase();

    if (status === "success" && data.result) {
      setResult(data.result);
      setError(null);
      setTaskId(null);
      setIsManuallyLoading(false);
      pollAttemptsRef.current = 0; // ← reset
    } else if (status === "failure") {
      setError(data.error ?? "后台任务失败，请检查日志。");
      setTaskId(null);
      setIsManuallyLoading(false);
      pollAttemptsRef.current = 0; // ← reset
    }
  }, [taskId, taskQuery.data]);

  useEffect(() => {
    if (!result) {
      setFeedbackTags([]);
      setFeedbackDraft("");
      return;
    }
    setFeedbackTags(autoTagSuggestions);
    if (autoTagSuggestions.length) {
      const autoText = autoTagSuggestions
        .map((tag) => FEEDBACK_TAGS[tag]?.text)
        .filter(Boolean)
        .join("\n");
      if (autoText) {
        setFeedbackDraft((prev) => (prev.trim() ? prev : autoText));
      }
    }
  }, [result, autoTagSuggestions]);

  const awaitingAsync = Boolean(taskId);
  const isSearching = useMemo(
    () =>
      isManuallyLoading ||
      searchMutation.isPending ||
      askMutation.isPending ||
      awaitingAsync ||
      taskQuery.isFetching ||
      taskQuery.isLoading,
    [
      isManuallyLoading,
      askMutation.isPending,
      searchMutation.isPending,
      awaitingAsync,
      taskQuery.isFetching,
      taskQuery.isLoading,
    ],
  );

  function executeSearch(
    nextQuery: string,
    feedbackOverride?: string,
    explicitTags?: string[],
  ) {
    const normalizedQuery = nextQuery.trim();
    if (!normalizedQuery || isSearching) return;
    setHasSearched(true);
    setResult(null);
    setError(null);
    setQuery(normalizedQuery);
    setSuggestions(DEFAULT_SUGGESTIONS);
    setIsManuallyLoading(true);

    // 清空上一次队列状态（防止残留 task 继续轮询）
    setTaskId(null);
    searchMutation.reset();
    askMutation.reset();

    const resolvedWebMode = (() => {
      if (searchOptions.allowWeb && searchOptions.docOnly) {
        return "upgrade";
      }
      if (searchOptions.allowWeb && !searchOptions.docOnly) {
        return "only";
      }
      if (searchOptions.docOnly && !searchOptions.allowWeb) {
        return "off";
      }
      return undefined;
    })();

    if (!feedbackOverride) {
      setFeedbackDraft("");
    }

    const clampedTopK = Math.min(Math.max(searchOptions.topK ?? 3, 3), 10);
    const effectiveFeedback = feedbackOverride?.trim();
    const tagPayload =
      effectiveFeedback && effectiveFeedback.length > 0
        ? (explicitTags ?? feedbackTags)
        : undefined;

    const payload: SearchRequestPayload = {
      query: normalizedQuery,
      docOnly: searchOptions.docOnly,
      allowWeb: searchOptions.allowWeb,
      webMode: resolvedWebMode,
      rerank: searchOptions.rerank,
      topK: clampedTopK,
      feedback: effectiveFeedback || undefined,
      feedbackTags: tagPayload && tagPayload.length ? tagPayload : undefined,
    };

    if (ENABLE_QUEUE) {
      askMutation.mutate(payload);
      return;
    }

    searchMutation.mutate(payload);
  }

  function handleSubmit(nextQuery: string) {
    executeSearch(nextQuery);
  }

  function handleFeedbackSubmit() {
    if (isSearching || !result) return;
    const normalizedFeedback = feedbackDraft.trim();
    if (!normalizedFeedback) return;
    if (!query.trim()) return;
    executeSearch(query, normalizedFeedback, feedbackTags);
    setFeedbackDraft("");
  }

  function handleClear() {
    resetSessionId();
    setQuery("");
    setResult(null);
    setError(null);
    setHasSearched(false);
    setTaskId(null);
    setSuggestions(DEFAULT_SUGGESTIONS);
    setIsManuallyLoading(false);
    setFeedbackDraft("");
    setFeedbackTags([]);
    pollAttemptsRef.current = 0; // ← reset
    searchMutation.reset();
    askMutation.reset();
  }

  const activeError =
    error ??
    (taskQuery.error instanceof Error ? taskQuery.error.message : null) ??
    null;

  const panelError =
    activeError ??
    (taskQuery.data?.status === "failure"
      ? taskQuery.data.error ?? "后台任务失败，请检查日志。"
      : null);

  useEffect(() => {
    if (result?.suggestions?.length) {
      const uniq = Array.from(new Set(result.suggestions)).slice(0, 5);
      setSuggestions(uniq.length ? uniq : DEFAULT_SUGGESTIONS);
    } else if (!result || result.mode === "doc") {
      setSuggestions(DEFAULT_SUGGESTIONS);
    } else {
      setSuggestions((prev) => prev.length ? prev : DEFAULT_SUGGESTIONS);
    }
  }, [result]);

  useEffect(() => {
    if (result) setIsManuallyLoading(false);
  }, [result]);

  // 查询中文档标题提示
  useEffect(() => {
    if (typeof document === "undefined") return;
    const original = document.title;
    document.title = isSearching ? "查询中… - RAG 系统" : "RAG 系统";
    return () => { document.title = original; };
  }, [isSearching]);

  const gridClass = cn(
    "mt-5 grid grid-cols-1 gap-6 transition-all duration-500 ease-in-out lg:items-stretch",
    sidebarHidden
      ? "lg:grid-cols-1 lg:justify-start"
      : "lg:grid-cols-[minmax(0,1fr)_minmax(0,360px)]",
  );

  const mainColumnClass = cn(
    "space-y-6 transition-all duration-500 ease-in-out lg:flex lg:flex-col lg:h-full",
    sidebarHidden ? "w-full" : "w-full max-w-4xl lg:max-w-5xl mx-auto",
  );

  return (
    <main className="min-h-screen floating-shapes">
      <div
        className={cn(
          "mx-auto px-6 py-6 transition-all duration-500 ease-in-out",
          "max-w-7xl"
        )}
      >
        <AppHeader
          sidebarHidden={sidebarHidden}
          onToggleSidebar={() => setSidebarHidden((prev) => !prev)}
        />
        <div className={gridClass}>
          <div className={mainColumnClass}>
            <SearchForm
              query={query}
              onQueryChange={setQuery}
              onSubmit={handleSubmit}
              onClear={handleClear}
              isSearching={isSearching}
              inputRef={searchInputRef}
              placeholder={suggestions[0] ?? DEFAULT_SUGGESTIONS[0]}
              suggestions={suggestions}
              onSuggestionClick={(value) => {
                setQuery(value);
                handleSubmit(value);
              }}
              options={searchOptions}
              onOptionsChange={setSearchOptions}
              focusMode={sidebarHidden}
            />
            <AnswerPanel
              result={result}
              isLoading={isSearching}
              error={panelError}
              hasSearched={hasSearched}
              onClear={handleClear}
              onSuggestionClick={(value) => {
                setQuery(value);
                handleSubmit(value);
              }}
              className="flex-1"
              focusMode={sidebarHidden}
            />
            <FeedbackForm
              value={feedbackDraft}
              onChange={setFeedbackDraft}
              onSubmit={handleFeedbackSubmit}
              disabled={isSearching}
              isSubmitting={isSearching}
              isVisible={Boolean(result)}
              history={result?.meta?.feedback_history ?? null}
              focusMode={sidebarHidden}
              selectedTags={feedbackTags}
              tagOptions={feedbackTagOptions}
            />
          </div>
          {!sidebarHidden && (
            <aside className="space-y-6 self-stretch transition-all duration-500 ease-in-out lg:sticky lg:top-16 lg:h-full">
              <IndexStatusCard />
              <EnhancedUploadCard />
            </aside>
          )}
        </div>
      </div>
    </main>
  );
}
