import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
  type MutableRefObject,
  type Dispatch,
  type SetStateAction,
} from "react";
import {
  AlertTriangle,
  BookOpen,
  Check,
  Copy,
  ExternalLink,
  Link2,
  Loader2,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Card } from "../common/card";
import { Tag } from "../common/tag";
import { SkeletonLine } from "../common/skeleton-line";
import { Alert, AlertDescription, AlertTitle } from "../ui/alert";
import { Badge } from "../ui/badge";
import { cn } from "../../lib/utils";
import type { Citation, SearchResponse } from "../../types/api";

interface AnswerPanelProps {
  result: SearchResponse | null;
  isLoading: boolean;
  error?: string | null;
  hasSearched: boolean;
  onClear: () => void;
  onSuggestionClick: (value: string) => void;
  className?: string;
  focusMode?: boolean;
}

interface ParsedSection {
  id: string;
  title: string;
  markdown: string;
  sources: string[];
  isOriginalExcerpt?: boolean;
  anchorId?: string;
  citationIndexes?: number[];
  count?: number;
}

function looksLikeMojibake(text: string): boolean {
  if (!text) return false;
  const s = text.trim();
  if (s.length < 6) return false;

  let cjk = 0;
  let basicLatin = 0;
  let latinSupp = 0;
  let replacement = 0;
  let punctOrSymbol = 0;
  let digit = 0;

  for (const ch of s) {
    const code = ch.charCodeAt(0);
    if (ch === "�") replacement++;
    if (code >= 0x4e00 && code <= 0x9fff) {
      cjk++;
    } else if ((code >= 0x41 && code <= 0x5a) || (code >= 0x61 && code <= 0x7a)) {
      basicLatin++;
    } else if (code >= 0xc0 && code <= 0x17f) {
      latinSupp++;
    } else if (code >= 0x30 && code <= 0x39) {
      digit++;
    } else if (
      (code >= 0x20 && code <= 0x2f) ||
      (code >= 0x3a && code <= 0x40) ||
      (code >= 0x5b && code <= 0x60) ||
      (code >= 0x7b && code <= 0x7f) ||
      (code >= 0x2000 && code <= 0x206f)
    ) {
      punctOrSymbol++;
    }
  }

  const total = s.length;
  if (cjk === 0 && (latinSupp > 0 || s.includes("Ã") || s.includes("Â"))) {
    const ratio = (basicLatin + latinSupp) / Math.max(total, 1);
    if (ratio > 0.7) return true;
  }
  if (replacement > 0 && replacement / Math.max(total, 1) > 0.05) return true;

  const lettersAndDigits = cjk + basicLatin + latinSupp + digit;
  const punctRatio = punctOrSymbol / Math.max(total, 1);
  if (lettersAndDigits <= 6 && punctRatio > 0.45) return true;
  if (lettersAndDigits > 0 && punctOrSymbol > 8 && punctRatio > 0.5) return true;

  const symbolHeavy = punctRatio > 0.35 && lettersAndDigits / Math.max(total, 1) < 0.65;
  if (symbolHeavy) return true;
  if (/[,，。\.、\-·…]{4,}/.test(s)) return true;
  if (punctOrSymbol >= 6 && punctOrSymbol > lettersAndDigits * 1.2) return true;
  if (/[，。．、；：!?\\-\\s\\u3000]{6,}/.test(s)) return true;

  if (/^(漫\\s*J口|C\\s*对男女慢性盆腔疼痛综合征)/i.test(s)) return true;

  return false;
}

export function AnswerPanel({
  result,
  isLoading,
  error,
  hasSearched,
  onClear,
  onSuggestionClick,
  className,
  focusMode = false,
}: AnswerPanelProps) {
  const [copiedAnswer, setCopiedAnswer] = useState(false);
  const [copiedSectionId, setCopiedSectionId] = useState<string | null>(null);
  const [highlightedCitationId, setHighlightedCitationId] = useState<
    string | null
  >(null);
  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>(
    {},
  );
  const citationRefs = useRef<Record<string, HTMLDivElement | null>>({});

  useEffect(() => {
    if (!copiedAnswer) return;
    const timer = setTimeout(() => setCopiedAnswer(false), 1_500);
    return () => clearTimeout(timer);
  }, [copiedAnswer]);

  useEffect(() => {
    if (!copiedSectionId) return;
    const timer = setTimeout(() => setCopiedSectionId(null), 1_200);
    return () => clearTimeout(timer);
  }, [copiedSectionId]);

  useEffect(() => {
    if (!highlightedCitationId) return;
    const timer = setTimeout(() => setHighlightedCitationId(null), 1_200);
    return () => clearTimeout(timer);
  }, [highlightedCitationId]);

  const citations = useMemo(() => {
    if (!result || result.mode !== "doc") {
      return [];
    }
    return (result.citations ?? [])
      .slice()
      .sort((a, b) => (b.score ?? 0) - (a.score ?? 0));
  }, [result]);

  const sections = useMemo<ParsedSection[]>(() => {
    if (!result?.answer) return [];
    const parsed = parseAnswerSections(result.answer);
    if (parsed.length > 0) {
      return parsed;
    }
    return [
      {
        id: "answer",
        title: result.mode === "doc" ? "回答" : "应答",
        markdown: result.answer,
        sources: [],
      },
    ];
  }, [result]);

  const moduleBadges = useMemo<ReactNode[]>(() => {
    const modules = result?.meta?.modules;
    if (!modules?.doc_only && !modules?.allow_web) {
      return [];
    }
    const docCount = result?.meta?.source_counts?.documents ?? 0;
    const webCount = result?.meta?.source_counts?.web ?? 0;
    const badges: ReactNode[] = [];
    if (modules.doc_only) {
      badges.push(
        <Badge
          key="badge-doc"
          variant="secondary"
          className="rounded-full px-3 py-1 text-[11px]"
        >
          仅文档回答{docCount ? ` · 证据 ${docCount}` : ""}
        </Badge>,
      );
    }
    if (modules.allow_web) {
      const label = modules.stacked ? "联网补充" : "联网检索";
      badges.push(
        <Badge
          key="badge-web"
          variant="outline"
          className="rounded-full px-3 py-1 text-[11px]"
        >
          {label}
          {webCount ? ` · 来源 ${webCount}` : ""}
        </Badge>,
      );
    }
    return badges;
  }, [result]);

  async function copyAnswer() {
    if (!result?.answer) return;
    try {
      await navigator.clipboard.writeText(result.answer);
      setCopiedAnswer(true);
    } catch (clipError) {
      console.error("Failed to copy answer", clipError);
    }
  }

  async function copySectionLink(sectionId: string) {
    if (typeof window === "undefined") return;
    try {
      const url = new URL(window.location.href);
      url.hash = sectionId;
      await navigator.clipboard.writeText(url.toString());
      window.history.replaceState(null, "", `#${sectionId}`);
      setCopiedSectionId(sectionId);
    } catch (clipError) {
      console.error("Failed to copy section link", clipError);
    }
  }

  function handleCitationTagClick(citationKey: string) {
    const target = citationRefs.current[citationKey];
    if (!target) return;
    target.scrollIntoView({ behavior: "smooth", block: "nearest" });
    setHighlightedCitationId(citationKey);
  }

  const content = (() => {
    if (isLoading) return <LoadingState />;
    if (error) {
      return (
        <Alert variant="destructive">
          <AlertTriangle className="h-5 w-5" aria-hidden="true" />
          <AlertTitle>查询失败</AlertTitle>
          <AlertDescription className="text-sm leading-7">
            {error}
            <br />
            请确认检索服务是否可用，或稍后再试。若持续失败，请检查后端日志。
          </AlertDescription>
        </Alert>
      );
    }

    if (result?.answer) {
      return (
        <AnswerContent
          result={result}
          sections={sections}
          citations={citations}
          copiedSectionId={copiedSectionId}
          highlightedCitationId={highlightedCitationId}
          citationRefs={citationRefs}
          onCopySectionLink={copySectionLink}
          onCitationTagClick={handleCitationTagClick}
          isFocusMode={focusMode}
          expandedSections={expandedSections}
          setExpandedSections={setExpandedSections}
        />
      );
    }

    if (hasSearched) {
      return (
        <Alert variant="default">
          <AlertTriangle className="h-5 w-5" aria-hidden="true" />
          <AlertTitle>文档库无匹配结果</AlertTitle>
          <AlertDescription className="text-sm leading-7">
            尝试添加更多上下文或限定文档范围，也可以启用通用模式 / 联网搜索获取更广泛的答案。
          </AlertDescription>
        </Alert>
      );
    }

    return <EmptyState />;
  })();

  return (
    <Card
      className={className}
      title={
        <div
          className={cn(
            "flex items-center gap-2 text-slate-700 dark:text-slate-100",
            focusMode && "text-lg md:text-xl"
          )}
        >
          <BookOpen className="h-5 w-5 text-brand-600 dark:text-brand-300" />
          回答
          {result?.mode === "general" && (
            <Badge variant="secondary" className="uppercase">
              [非文档知识]
            </Badge>
          )}
        </div>
      }
      extra={
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={copyAnswer}
            disabled={!result?.answer}
            className={cn(
              "inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-60 dark:border-white/10 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800",
              focusMode && "px-4 py-2 text-sm"
            )}
            aria-label="复制当前回答"
          >
            {copiedAnswer ? (
              <>
                <Check className="h-4 w-4" aria-hidden="true" />
                已复制
              </>
            ) : (
              <>
                <Copy className="h-4 w-4" aria-hidden="true" />
                复制
              </>
            )}
          </button>
          <button
            type="button"
            onClick={onClear}
            disabled={!result && !hasSearched}
            className={cn(
              "inline-flex items-center gap-2 rounded-lg border border-transparent px-3 py-1.5 text-xs font-medium text-slate-500 transition hover:text-slate-700 disabled:cursor-not-allowed disabled:opacity-50 dark:text-slate-300 dark:hover:text-slate-100",
              focusMode && "px-4 py-2 text-sm"
            )}
          >
            清空
          </button>
        </div>
      }
      contentClassName={cn("space-y-6", focusMode && "text-[15px] leading-relaxed")}
    >
      {moduleBadges.length > 0 && (
        <div
          className={cn(
            "mb-2 flex flex-wrap gap-2 text-xs text-slate-600 dark:text-slate-300",
            focusMode && "text-sm"
          )}
        >
          {moduleBadges}
        </div>
      )}
      {content}

      {result?.suggestions?.length ? (
        <SuggestionList
          suggestions={result.suggestions}
          onSuggestionClick={onSuggestionClick}
          isLoading={isLoading}
        />
      ) : null}
    </Card>
  );
}

function AnswerContent({
  result,
  sections,
  citations,
  copiedSectionId,
  highlightedCitationId,
  citationRefs,
  onCopySectionLink,
  onCitationTagClick,
  isFocusMode,
  expandedSections,
  setExpandedSections,
}: {
  result: SearchResponse;
  sections: ParsedSection[];
  citations: Citation[];
  copiedSectionId: string | null;
  highlightedCitationId: string | null;
  citationRefs: MutableRefObject<Record<string, HTMLDivElement | null>>;
  onCopySectionLink: (sectionId: string) => void;
  onCitationTagClick: (id: string) => void;
  isFocusMode: boolean;
  expandedSections: Record<string, boolean>;
  setExpandedSections: Dispatch<SetStateAction<Record<string, boolean>>>;
}) {
  const sectionDetails = useMemo(() => {
    return sections
      .map((section, index) => {
        const citationIndexes =
          result.mode === "doc"
            ? matchCitations(section, citations)
            : citations.map((_, citationIndex) => citationIndex);
      const count =
        citationIndexes.filter((idx) => idx >= 0).length ||
        section.sources.filter(
          (item) => !item.includes("未检索到可靠来源"),
        ).length;

      const normalizedTitle = section.title.replace(/\s+/g, "");
      const anchorId = section.id || `section-${index + 1}`;
      const isOriginalExcerpt = normalizedTitle.includes("原文摘录（更多细节）");
      const baseDetails: ParsedSection & {
        anchorId: string;
        citationIndexes: number[];
      } = {
        ...section,
        anchorId,
        citationIndexes,
        count,
        isOriginalExcerpt,
      };
      if (isOriginalExcerpt) {
        const lines = section.markdown
          .split(/\n+/)
          .map((line) => line.trim())
          .filter((line) => Boolean(line) && !looksLikeMojibake(line.replace(/^[-•]\s*/, "")));
        if (lines.length > 1) {
          return lines.map((line, lineIndex) => ({
            ...baseDetails,
            id: `${section.id}-line-${lineIndex}`,
            anchorId: `${anchorId}-line-${lineIndex}`,
            title: lineIndex === 0 ? section.title : "",
            markdown: line.replace(/^[-•]\s*/, ""),
          }));
        }
        if (lines.length === 0) {
          return [];
        }
      }
      return baseDetails;
      })
      .flat();
  }, [sections, citations, result.mode]);

  const excerptInfo = useMemo(() => {
    const thresholds = result.diagnostics?.retrieval_thresholds;
    const excerptDiag = result.diagnostics?.excerpt_retrieval;
    const summaryDiag = result.diagnostics?.summary_retrieval;
    const excerptThreshold =
      typeof excerptDiag?.confidence_threshold === "number"
        ? excerptDiag.confidence_threshold
        : typeof thresholds?.excerpt === "number"
          ? thresholds.excerpt
          : undefined;
    const summaryThreshold =
      typeof summaryDiag?.confidence_threshold === "number"
        ? summaryDiag.confidence_threshold
        : typeof thresholds?.summary === "number"
          ? thresholds.summary
          : undefined;
    const summaryHits =
      typeof summaryDiag?.hits === "number" ? summaryDiag.hits : undefined;
    const summaryTotal =
      typeof summaryDiag?.total === "number" ? summaryDiag.total : undefined;
    const excerptTopK =
      typeof excerptDiag?.final_top_k === "number"
        ? excerptDiag.final_top_k
        : typeof excerptDiag?.requested_top_k === "number"
          ? excerptDiag.requested_top_k
          : undefined;
    const summaryLimited =
      typeof summaryHits === "number" &&
      typeof summaryTotal === "number" &&
      summaryHits < summaryTotal;
    return {
      excerptThreshold,
      summaryThreshold,
      summaryHits,
      summaryTotal,
      excerptTopK,
      summaryLimited,
      error: excerptDiag?.error,
      hasData:
        typeof excerptThreshold === "number" ||
        typeof excerptTopK === "number" ||
        typeof summaryThreshold === "number" ||
        typeof summaryHits === "number" ||
        typeof summaryTotal === "number" ||
        Boolean(excerptDiag?.error),
    };
  }, [result]);

  return (
    <div className={cn("space-y-5", isFocusMode && "space-y-6 text-[15px]")}>
      <div className="space-y-4">
        {sectionDetails.map((section) => {
          const isOriginalExcerpt = Boolean(section.isOriginalExcerpt);
          return (
          <article
            key={section.anchorId}
            id={section.anchorId}
            className={cn(
              "rounded-xl border border-slate-200/60 bg-white/80 p-5 shadow-sm transition dark:border-white/10 dark:bg-slate-900/60",
              isFocusMode && "p-6"
            )}
          >
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
              {!!section.title && (
                <h4
                  className={cn(
                    "text-base font-semibold text-slate-800 dark:text-slate-100",
                    isFocusMode && "text-lg"
                  )}
                >
                  {section.title}
                </h4>
              )}
              <div className="flex items-center gap-2">
                <Tag asSpan className={isFocusMode ? "text-sm px-3 py-1.5" : undefined}>
                  { (section.count ?? 0) > 0 ? `${section.count} Sources` : "暂无来源"}
                </Tag>
                <button
                  type="button"
                  onClick={() => onCopySectionLink(section.anchorId)}
                  className={cn(
                    "inline-flex items-center gap-1 text-xs text-slate-500 transition hover:text-slate-700 dark:text-slate-300 dark:hover:text-slate-100",
                    isFocusMode && "text-sm"
                  )}
                >
                  <Link2 className="h-3.5 w-3.5" aria-hidden="true" />
                  {copiedSectionId === section.anchorId ? "已复制" : "复制链接"}
                </button>
              </div>
            </div>
            {isOriginalExcerpt && excerptInfo.hasData ? (
              <div
                className={cn(
                  "mb-2 flex flex-wrap items-center gap-2 text-xs text-slate-500 dark:text-slate-300",
                  isFocusMode && "text-sm"
                )}
              >
                {typeof excerptInfo.summaryThreshold === "number" ? (
                  <Tag
                    asSpan
                    className="bg-slate-50 text-slate-700 dark:bg-slate-800 dark:text-slate-100"
                  >
                    摘要阈值 {excerptInfo.summaryThreshold.toFixed(2)}
                  </Tag>
                ) : null}
                {typeof excerptInfo.summaryHits === "number" ? (
                  <span>
                    高置信片段 {excerptInfo.summaryHits}
                    {typeof excerptInfo.summaryTotal === "number"
                      ? `/${excerptInfo.summaryTotal}`
                      : ""}
                  </span>
                ) : null}
                {excerptInfo.summaryLimited ? (
                  <span className="text-amber-600 dark:text-amber-300">
                    低于阈值的片段仅在原文摘录中展示
                  </span>
                ) : null}
                <Tag
                  asSpan
                  className="bg-slate-50 text-slate-600 dark:bg-slate-800 dark:text-slate-200"
                >
                  低阈值检索
                </Tag>
                {typeof excerptInfo.excerptThreshold === "number" ? (
                  <span>阈值 {excerptInfo.excerptThreshold.toFixed(2)}</span>
                ) : null}
                {typeof excerptInfo.excerptTopK === "number" ? (
                  <span>展示 Top {excerptInfo.excerptTopK}</span>
                ) : null}
                {excerptInfo.error ? (
                  <span className="text-amber-600 dark:text-amber-300">
                    {excerptInfo.error}
                  </span>
                ) : null}
              </div>
            ) : null}
            {isOriginalExcerpt ? (
              <div className="mt-1 space-y-2">
                {(() => {
                  const expanded = expandedSections[section.anchorId] ?? false;
                  const shouldCollapse = Boolean(section.markdown);
                  return (
                    <>
                      <div
                        className={cn(
                          "relative overflow-hidden rounded-lg border border-slate-100/60 bg-white p-3 shadow-inner dark:border-white/5 dark:bg-slate-900/40",
                          !expanded && "max-h-40"
                        )}
                      >
                        {!expanded && shouldCollapse && (
                          <div className="pointer-events-none absolute inset-x-0 bottom-0 h-14 bg-gradient-to-t from-slate-50 via-slate-50/70 to-transparent dark:from-slate-900 dark:via-slate-900/70" />
                        )}
                        <ReactMarkdown>
                          {section.markdown}
                        </ReactMarkdown>
                      </div>
                      {shouldCollapse && (
                        <button
                          type="button"
                          onClick={() =>
                            setExpandedSections((prev) => ({
                              ...prev,
                              [section.anchorId]: !expanded,
                            }))
                          }
                          className={cn(
                            "inline-flex items-center gap-1 rounded-full border border-brand-500/70 bg-white px-3 py-1 text-xs font-medium text-brand-600 shadow transition hover:bg-slate-50 dark:border-brand-300/70 dark:bg-slate-900 dark:text-brand-200",
                            isFocusMode && "text-sm"
                          )}
                        >
                          {expanded ? "收起原文" : "展开更多"}
                        </button>
                      )}
                    </>
                  );
                })()}
              </div>
            ) : (
              <div
                className={cn(
                  "answer-markdown prose prose-slate max-w-none text-sm leading-7 dark:prose-invert",
                  isFocusMode && "text-base leading-8"
                )}
              >
                <ReactMarkdown>
                  {section.markdown}
                </ReactMarkdown>
              </div>
            )}
            {section.sources.length > 0 ? (
              <footer className="mt-4 flex flex-wrap gap-2">
                {section.sources.map((item) => (
                  <Tag
                    asSpan
                    key={item}
                    className={isFocusMode ? "text-sm px-3 py-1.5" : undefined}
                  >
                    {item.replace(/^\s*[-*]\s*/, "")}
                  </Tag>
                ))}
              </footer>
            ) : null}
          </article>
        );
        })}
      </div>

      {result.mode === "doc" && citations.length > 0 ? (
        <SourcesPanel
          citations={citations}
          sectionDetails={sectionDetails}
          highlightedCitationId={highlightedCitationId}
          citationRefs={citationRefs}
          onCitationTagClick={onCitationTagClick}
          isFocusMode={isFocusMode}
        />
      ) : null}
    </div>
  );
}

function SourcesPanel({
  citations,
  sectionDetails,
  highlightedCitationId,
  citationRefs,
  onCitationTagClick,
  isFocusMode,
}: {
  citations: Citation[];
  sectionDetails: (ParsedSection & {
    anchorId: string;
    citationIndexes: number[];
  })[];
  highlightedCitationId: string | null;
  citationRefs: MutableRefObject<Record<string, HTMLDivElement | null>>;
  onCitationTagClick: (id: string) => void;
  isFocusMode: boolean;
}) {
  const uniqueCitationIds = citations.map((_, index) => `citation-${index}`);

  const sectionToCitationMap = useMemo(() => {
    const mapping: Record<string, number[]> = {};
    sectionDetails.forEach((section) => {
      mapping[section.anchorId] = section.citationIndexes.filter(
        (idx) => idx >= 0,
      );
    });
    return mapping;
  }, [sectionDetails]);

  const matchedCitationIndexes = Array.from(
    new Set(Object.values(sectionToCitationMap).flat()),
  ).filter((idx) => idx >= 0);

  return (
    <section
      className={cn(
        "space-y-3 rounded-xl border border-slate-200/60 bg-slate-50/60 p-4 dark:border-white/10 dark:bg-slate-900/40",
        isFocusMode && "p-5"
      )}
    >
      <div className="flex items-center justify-between">
        <h5
          className={cn(
            "text-sm font-semibold text-slate-700 dark:text-slate-200",
            isFocusMode && "text-base"
          )}
        >
          参考来源
        </h5>
        <span
          className={cn(
            "text-xs text-slate-500 dark:text-slate-400",
            isFocusMode && "text-sm"
          )}
        >
          点击 Chip 会定位到对应证据
        </span>
      </div>

      <div className="flex flex-wrap gap-2">
        {matchedCitationIndexes.length > 0 ? (
          matchedCitationIndexes.map((citationIndex) => {
            const citation = citations[citationIndex];
            const id = uniqueCitationIds[citationIndex];
            return (
              <Tag
                key={id}
                onClick={() => onCitationTagClick(id)}
                className={cn(
                  "capitalize",
                  isFocusMode && "text-sm px-3 py-1.5"
                )}
              >
                {formatCitationLabel(citation)}
              </Tag>
            );
          })
        ) : (
          <Tag asSpan className={isFocusMode ? "text-sm px-3 py-1.5" : undefined}>
            未检索到可靠来源
          </Tag>
        )}
      </div>

      <div className="space-y-3">
        {citations.map((citation, index) => {
          const citationId = uniqueCitationIds[index];
          return (
            <div
              key={citationId}
              ref={(node) => {
                citationRefs.current[citationId] = node;
              }}
              className={cn(
                "rounded-xl border border-slate-200/60 bg-white p-4 text-sm transition dark:border-white/10 dark:bg-slate-900",
                highlightedCitationId === citationId &&
                  "ring-2 ring-brand-500/60 ring-offset-2 ring-offset-white dark:ring-offset-slate-950",
              )}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="font-semibold text-slate-800 dark:text-slate-100">
                  {citation.url ? (
                    <a
                      href={citation.url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1 text-brand-600 hover:underline dark:text-brand-300"
                    >
                      {citation.title || citation.source || "网页来源"}
                      <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
                    </a>
                  ) : (
                    citation.title || citation.source || "未知来源"
                  )}
                </p>
                <div className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-300">
                  {typeof citation.page === "number" ? (
                    <span className="rounded-full bg-slate-100 px-2 py-0.5 dark:bg-slate-800">
                      P.{citation.page}
                    </span>
                  ) : null}
                  {typeof citation.score === "number" ? (
                    <span className="rounded-full bg-brand-500/10 px-2 py-0.5 text-brand-600 dark:bg-brand-500/20 dark:text-brand-200">
                      相关性 {(citation.score * 100).toFixed(0)}%
                    </span>
                  ) : null}
                </div>
              </div>
              {citation.snippet ? (
                <p
                  className={cn(
                    "reference-snippet mt-3 text-slate-600 dark:text-slate-300",
                    isFocusMode && "text-base"
                  )}
                >
                  {citation.snippet}
                </p>
              ) : null}
              {citation.url ? (
                <a
                  href={citation.url}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-3 inline-flex items-center gap-1 text-sm font-medium text-brand-600 hover:underline dark:text-brand-300"
                >
                  前往原文
                  <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
                </a>
              ) : null}
            </div>
          );
        })}
      </div>
    </section>
  );
}

function SuggestionList({
  suggestions,
  onSuggestionClick,
  isLoading,
}: {
  suggestions: string[];
  onSuggestionClick: (value: string) => void;
  isLoading: boolean;
}) {
  if (!suggestions.length) return null;
  return (
    <div className="space-y-2">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">
        还可以这样问
      </p>
      <div className="flex flex-wrap gap-2">
        {suggestions.slice(0, 5).map((item) => (
          <Tag
            key={item}
            className="text-xs"
            onClick={() => {
              if (isLoading) return;
              onSuggestionClick(item);
            }}
            disabled={isLoading}
          >
            {item}
          </Tag>
        ))}
      </div>
    </div>
  );
}

function LoadingState() {
  return (
    <div className="space-y-4" aria-live="polite">
      <div className="flex items-center gap-2 text-sm text-slate-500 dark:text-slate-300">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        正在检索，请稍候…
      </div>
      <SkeletonLine w="80%" />
      <SkeletonLine w="65%" />
      <SkeletonLine w="90%" />
      <SkeletonLine w="55%" />
    </div>
  );
}

function EmptyState() {
  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-500 dark:text-slate-300">
        输入问题并按 Enter 或点击“搜索”即可开始检索。示例：
      </p>
      <ul className="list-inside list-disc text-sm leading-7 text-slate-500 dark:text-slate-300">
        <li>这份安全手册的关键条款是什么？</li>
        <li>最新报表里提到的营收增长驱动有哪些？</li>
        <li>会议纪要里关于新项目的行动项。</li>
      </ul>
    </div>
  );
}

function parseAnswerSections(answer: string): ParsedSection[] {
  const trimmed = normalizeAnswerRoot(answer);
  if (!trimmed) return [];

  const segments = trimmed
    .split(/\n(?=###\s+)/)
    .map((segment) => segment.trim())
    .filter(Boolean);
  if (segments.length === 0 && trimmed.startsWith("###")) {
    segments.push(trimmed);
  }

  if (segments.length === 0) {
    return [];
  }

  const parsed = segments.map((segment, index) => {
    const lines = segment.trim().split("\n");
    let heading = normalizeHeadingLine(lines[0] ?? "");
    let contentStart = 0;
    if (heading.startsWith("###")) {
      contentStart = 1;
      heading = heading.replace(/^###\s*/, "").trim();
    } else {
      heading = heading || `主题 ${index + 1}`;
    }

    const sourceIndex = lines.findIndex((line) => {
      const normalized = line.trim().replace(/：/g, ":");
      return normalized === "来源:" || normalized === "来源";
    });

    const bodyLines =
      sourceIndex >= 0
        ? lines.slice(contentStart, sourceIndex)
        : lines.slice(contentStart);

    const sources =
      sourceIndex >= 0
        ? lines
            .slice(sourceIndex + 1)
            .map((line) => line.trim())
            .filter(Boolean)
        : [];

    const markdown = bodyLines.join("\n").replace(/^\ufeff+/, "").trim();

    return {
      id: `topic-${index + 1}`,
      title: heading,
      markdown,
      sources,
    };
  });

  // 去重：避免后端偶发重复段落时前端显示两份
  const deduped: ParsedSection[] = [];
  const seen = new Set<string>();
  for (const item of parsed) {
    const key = `${item.title}::${item.markdown}`;
    if (seen.has(key)) continue;
    seen.add(key);
    deduped.push(item);
  }

  return deduped;
}

function normalizeAnswerRoot(answer: string): string {
  if (!answer) return "";
  let normalized = answer.replace(/^\ufeff+/, "").trim();
  const headingIndex = normalized.indexOf("###");
  if (headingIndex > 0 && headingIndex < 8) {
    const prefix = normalized.slice(0, headingIndex).trim();
    if (prefix.length <= 2) {
      normalized = normalized.slice(headingIndex);
    }
  }
  return normalized;
}

function normalizeHeadingLine(line: string): string {
  const trimmed = line.trim();
  if (!trimmed) return trimmed;
  if (trimmed.startsWith("###")) return trimmed;
  const idx = trimmed.indexOf("###");
  if (idx > 0 && idx < 5) {
    return trimmed.slice(idx).trim();
  }
  return trimmed;
}

function matchCitations(section: ParsedSection, citations: Citation[]) {
  if (!citations.length) return [];
  const result: number[] = [];

  section.sources.forEach((sourceLine) => {
    const cleaned = sourceLine
      .replace(/^\s*[-*]\s*/, "")
      .replace(/\[[^\]]*\]\s*/g, "")
      .trim();
    if (!cleaned || cleaned.includes("未检索到可靠来源")) return;

    const matchIndex = citations.findIndex(
      (citation, index) =>
        !result.includes(index) &&
        cleaned.toLowerCase().includes(
          (citation.source ?? "").toLowerCase(),
        ),
    );
    if (matchIndex >= 0) {
      result.push(matchIndex);
    }
  });

  return result;
}

function formatCitationLabel(citation: Citation): ReactNode {
  const pieces: string[] = [];
  const mainTitle = citation.title || citation.source;
  if (mainTitle) {
    pieces.push(mainTitle);
  }
  if (typeof citation.page === "number") {
    pieces.push(`P.${citation.page}`);
  }
  return pieces.join(" · ") || "未知来源";
}
