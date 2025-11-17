import { useQuery } from "@tanstack/react-query";
import { AlertCircle, Loader2, RefreshCcw } from "lucide-react";
import { Card } from "../common/card";
import { SkeletonLine } from "../common/skeleton-line";
import { getIndexStatus } from "../../services/api";
import { cn } from "../../lib/utils";

function formatDate(value?: string) {
  if (!value) return "未更新";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function IndexStatusCard() {
  const {
    data,
    error,
    isError,
    isLoading,
    isFetching,
    refetch,
  } = useQuery({
    queryKey: ["index-status"],
    queryFn: getIndexStatus,
    refetchInterval: 15_000,
  });

  const isInitialLoading = isLoading && !data;

  const expectedChunks =
    data && data.documents > 0 ? data.documents * 300 : undefined;
  const chunkProgress = expectedChunks
    ? Math.max(
        0,
        Math.min(100, Math.round(((data?.chunks ?? 0) / expectedChunks) * 100)),
      )
    : 0;

  return (
    <Card
      title="索引状态"
      extra={
        <button
          type="button"
          onClick={() => refetch()}
          aria-label="刷新索引状态"
          className="glass-effect rounded-full p-2 text-white/80 hover:text-white transition-colors"
          disabled={isFetching}
        >
          {isFetching ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          ) : (
            <RefreshCcw className="h-4 w-4" aria-hidden="true" />
          )}
        </button>
      }
      aria-live="polite"
      aria-busy={isFetching}
    >
      {isInitialLoading ? (
        <div className="space-y-3">
          <SkeletonLine />
          <SkeletonLine w="80%" />
          <SkeletonLine w="60%" />
        </div>
      ) : isError ? (
        <div
          className="flex items-start gap-3 rounded-xl border border-red-200/60 bg-red-50/60 p-3 text-sm text-red-700 dark:border-red-400/30 dark:bg-red-950/30 dark:text-red-100"
          role="alert"
        >
          <AlertCircle className="h-5 w-5" aria-hidden="true" />
          <div>
            <p className="font-semibold">无法获取索引状态</p>
            <p className="mt-1 text-xs">
              {error instanceof Error
                ? error.message
                : "请稍后重试，或检查后端服务是否已启动。"}
            </p>
          </div>
        </div>
      ) : (
        <>
          <div className="space-y-4">
            <div className="flex flex-wrap justify-center gap-4">
              <StatusMetric
                label="DOCUMENTS"
                value={data?.documents ?? 0}
                className="min-w-[150px] max-w-[200px] flex-1"
              />
              <StatusMetric
                label="CHUNKS"
                value={data?.chunks ?? 0}
                className="min-w-[150px] max-w-[200px] flex-1"
              />
            </div>
            <div className="flex justify-center">
              <StatusMetric
                label="LAST UPDATED"
                value={formatDate(data?.updated_at)}
                emphasize={false}
                className="w-full max-w-[320px]"
              />
            </div>
          </div>
          <div className="mt-4">
            <div className="h-1.5 rounded-full bg-slate-200 dark:bg-slate-800">
              <div
                className="h-1.5 rounded-full bg-brand-600 transition-all"
                style={{ width: `${chunkProgress}%` }}
              />
            </div>
            <div className="mt-2 text-xs text-white/80">
              构建进度 {chunkProgress}% · 每 15 秒自动刷新
            </div>
          </div>
        </>
      )}
    </Card>
  );
}

interface StatusMetricProps {
  label: string;
  value: number | string;
  emphasize?: boolean;
  className?: string;
}

function StatusMetric({ label, value, emphasize = true, className }: StatusMetricProps) {
  return (
    <div
      className={cn(
        "glass-effect rounded-2xl bg-white/85 p-4 text-center text-[#2b174d]",
        className,
      )}
    >
      <div
        className={cn(
          emphasize
            ? "text-2xl font-semibold text-[#2b174d]"
            : "text-base font-medium text-[#5a3a7b]",
        )}
      >
        {value}
      </div>
      <div className="mt-1 text-xs font-semibold tracking-wide text-[#8151aa] uppercase">
        {label}
      </div>
    </div>
  );
}
