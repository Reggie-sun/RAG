import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import React from "react";
import {
  AlertCircle,
  Check,
  FileUp,
  Loader2,
  UploadCloud,
  Trash2,
  RefreshCw,
  History,
} from "lucide-react";
import {
  ChangeEvent,
  DragEvent,
  useCallback,
  useRef,
  useState,
} from "react";
import { Button } from "../ui/button";
import { Label } from "../ui/label";
import { Progress } from "../ui/progress";
import { Alert, AlertDescription, AlertTitle } from "../ui/alert";
import { Badge } from "../ui/badge";
import { Card } from "../common/card";
import { Tag } from "../common/tag";
import { cn } from "../../lib/utils";
import { uploadDocuments, clearIndex, getIndexStatus } from "../../services/api";
import type { UploadSummary, IndexStatus } from "../../types/api";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "../ui/alert-dialog";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "../ui/tooltip";

const ACCEPTED_EXTENSIONS = [
  ".pdf",
  ".txt",
  ".docx",
  ".odt",
  ".png",
  ".jpg",
  ".jpeg",
  ".bmp",
  ".tiff",
  ".tif",
  ".webp",
  ".doc",
];

const ACCEPTED_TYPES = [
  "application/pdf",
  "text/plain",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/msword",
  "application/vnd.oasis.opendocument.text",
  "image/png",
  "image/jpeg",
  "image/bmp",
  "image/tiff",
  "image/webp",
];

interface EnhancedUploadCardProps {
  onUploaded?: () => void;
}

const MAX_FILES_PER_BATCH = 3;

export function EnhancedUploadCard({ onUploaded }: EnhancedUploadCardProps) {
  const [progress, setProgress] = useState<number>(0);
  const [isDragActive, setIsDragActive] = useState(false);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [customError, setCustomError] = useState<string | null>(null);
  const [recentUploads, setRecentUploads] = useState<UploadSummary[]>([]);
  const [allUploadedFiles, setAllUploadedFiles] = useState<UploadSummary[]>([]);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const queryClient = useQueryClient();

  // 获取索引状态，包括当前已上传的文件信息
const { data: indexStatus, refetch: refetchIndexStatus } = useQuery<IndexStatus>({
    queryKey: ["index-status"],
    queryFn: getIndexStatus,
    refetchInterval: 30000, // 30秒刷新一次
  });

  // 模拟获取已上传文件列表（因为当前API不返回具体文件列表）
  // 这里我们可以使用本地状态来累积显示
  React.useEffect(() => {
    if (recentUploads.length > 0) {
      setAllUploadedFiles(prev => {
        const newFiles = recentUploads.filter(
          newFile => !prev.some(existingFile => existingFile.filename === newFile.filename)
        );
        return [...prev, ...newFiles];
      });
    }
  }, [recentUploads]);

  const uploadMutation = useMutation({
    mutationFn: (files: File[]) => uploadDocuments(files, setProgress),
    onSuccess: (data) => {
      setSuccessMessage(`已索引 ${data.processed.length} 个文件`);
      setRecentUploads(data.processed);
      setCustomError(null);
      queryClient.invalidateQueries({ queryKey: ["index-status"] });
      refetchIndexStatus();
      onUploaded?.();
    },
    onError: (error) => {
      setSuccessMessage(null);
      setRecentUploads([]);
      if (error instanceof Error) {
        setCustomError(error.message);
      }
    },
    onSettled: () => {
      setTimeout(() => setProgress(0), 1_000);
    },
  });

  const clearIndexMutation = useMutation({
    mutationFn: clearIndex,
    onSuccess: () => {
      setSuccessMessage("索引已清空");
      setAllUploadedFiles([]);
      setRecentUploads([]);
      setCustomError(null);
      queryClient.invalidateQueries({ queryKey: ["index-status"] });
      refetchIndexStatus();
      onUploaded?.();
    },
    onError: (error) => {
      setCustomError(error instanceof Error ? error.message : "清空索引失败");
    },
    onSettled: () => {
      setTimeout(() => setSuccessMessage(null), 3_000);
    },
  });

  const resetDragState = useCallback(() => setIsDragActive(false), []);

  const handleFiles = useCallback(
    (files: FileList | null) => {
      if (!files || files.length === 0) return;

      const fileArray = Array.from(files).slice(0, MAX_FILES_PER_BATCH);
      const unsupported = fileArray.find((file) => {
        if (!file.type) return false;
        const extension = `.${file.name.split(".").pop()?.toLowerCase() ?? ""}`;
        return !ACCEPTED_TYPES.includes(file.type) && !ACCEPTED_EXTENSIONS.includes(extension);
      });

      if (unsupported) {
        uploadMutation.reset();
        setSuccessMessage(null);
        setCustomError("包含不支持的文件类型，请选择 PDF/TXT/DOCX/ODT 或图片格式。");
        return;
      }

      if (files.length > MAX_FILES_PER_BATCH) {
        setCustomError(`单次最多上传 ${MAX_FILES_PER_BATCH} 个文件，已自动截取前 ${MAX_FILES_PER_BATCH} 个。`);
      } else {
        setCustomError(null);
      }

      setSuccessMessage(null);
      uploadMutation.mutate(fileArray);
    },
    [uploadMutation],
  );

  const onDrop = useCallback(
    (event: DragEvent<HTMLLabelElement>) => {
      event.preventDefault();
      event.stopPropagation();
      resetDragState();
      handleFiles(event.dataTransfer.files);
    },
    [handleFiles, resetDragState],
  );

  const onDragEnter = useCallback((event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    event.stopPropagation();
    setIsDragActive(true);
  }, []);

  const onDragLeave = useCallback((event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    event.stopPropagation();
    if (event.currentTarget.contains(event.relatedTarget as Node)) return;
    resetDragState();
  }, [resetDragState]);

  const onDragOver = useCallback((event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    event.stopPropagation();
    if (!isDragActive) setIsDragActive(true);
  }, [isDragActive]);

  const triggerFileSelect = useCallback(() => {
    fileInputRef.current?.click();
  }, []);

  const onFileChange = useCallback(
    (event: ChangeEvent<HTMLInputElement>) => {
      handleFiles(event.target.files);
      event.target.value = "";
    },
    [handleFiles],
  );

  const isUploading = uploadMutation.isPending;
  const isClearing = clearIndexMutation.isPending;

  return (
    <div className="space-y-6">
      {/* 上传区域 */}
      <Card
        aria-live="polite"
        title="上传新文档"
        extra={
          <div className="flex items-center gap-2">
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => refetchIndexStatus()}
                    disabled={isUploading || isClearing}
                    className="gradient-button !px-4 !py-2 text-xs"
                  >
                    <RefreshCw className="h-4 w-4 mr-1" />
                    刷新
                  </Button>
                </TooltipTrigger>
                <TooltipContent>
                  <p>刷新索引状态</p>
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>

            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={
                    isUploading ||
                    isClearing ||
                    !indexStatus ||
                    indexStatus.documents === 0
                  }
                  className="rounded-full bg-rose-500/85 px-4 py-2 text-xs font-semibold text-white shadow-lg shadow-rose-500/30 hover:bg-rose-500 disabled:opacity-50"
                >
                  <Trash2 className="h-4 w-4 mr-1" />
                  清空
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>确认清空索引？</AlertDialogTitle>
                  <AlertDialogDescription>
                    此操作将删除所有已上传的文档、向量索引和搜索数据。此操作不可恢复。
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>取消</AlertDialogCancel>
                  <AlertDialogAction
                    onClick={() => clearIndexMutation.mutate()}
                    disabled={isClearing}
                  >
                    {isClearing ? (
                      <>
                        <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                        清空中...
                      </>
                    ) : (
                      "确认清空"
                    )}
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          </div>
        }
      >
        <div className="space-y-4 text-[#2b174d]">
          <p className="text-sm">
            支持 PDF、TXT、DOCX 以及常见图片格式，上传后自动执行拆分与向量化。
            当前索引：{indexStatus?.documents || 0} 个文档 ·{" "}
            {indexStatus?.chunks || 0} 个切片。
          </p>
          <input
            ref={fileInputRef}
            type="file"
            className="hidden"
            onChange={onFileChange}
            multiple
            accept={ACCEPTED_EXTENSIONS.join(",")}
          />
          <Label
            htmlFor="rag-uploader"
            onDragEnter={onDragEnter}
            onDragLeave={onDragLeave}
            onDragOver={onDragOver}
            onDrop={onDrop}
            tabIndex={0}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                triggerFileSelect();
              }
            }}
            className={cn(
              "flex cursor-pointer flex-col items-center justify-center gap-3 rounded-2xl border-2 border-dashed border-[#d5b5ff] bg-white/90 p-8 text-center text-[#2b174d] transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#c69bff]/50",
              "dark:border-white/20 dark:bg-black/30 dark:text-white",
              isDragActive && "border-[#a367ff] bg-white",
            )}
            aria-label="拖拽或点击上传文件"
          >
            <UploadCloud className="h-8 w-8 text-[#7a2cd1]" />
            <div className="space-y-1 text-sm">
              <p className="font-medium text-[#2b174d]">
                拖拽文件到此，或{" "}
                <button
                  type="button"
                  onClick={(event) => {
                    event.preventDefault();
                    triggerFileSelect();
                  }}
                  className="text-[#7a2cd1] underline decoration-dashed underline-offset-4"
                >
                  选择文件
                </button>
              </p>
              <p className="text-xs text-[#5c3f81]">
                支持 PDF / TXT / DOCX / ODT / PNG / JPG / BMP / TIFF / WEBP，单次最多 {MAX_FILES_PER_BATCH} 个文件
              </p>
            </div>
          </Label>

          {recentUploads.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {recentUploads.map((file) => (
                <Tag key={file.filename}>{file.filename}</Tag>
              ))}
            </div>
          )}

          {isUploading && (
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-sm text-white/80">
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                文档上传中，请勿关闭页面…
              </div>
              <Progress value={progress} className="h-2" />
            </div>
          )}

          {uploadMutation.isSuccess && successMessage && (
            <Alert variant="success">
              <Check className="h-4 w-4" aria-hidden="true" />
              <AlertTitle>上传成功</AlertTitle>
              <AlertDescription className="text-sm text-emerald-600 dark:text-emerald-400">
                {successMessage}
              </AlertDescription>
            </Alert>
          )}

          {clearIndexMutation.isSuccess && successMessage && (
            <Alert variant="success">
              <Check className="h-4 w-4" aria-hidden="true" />
              <AlertTitle>操作成功</AlertTitle>
              <AlertDescription className="text-sm text-emerald-600 dark:text-emerald-400">
                {successMessage}
              </AlertDescription>
            </Alert>
          )}

          {(uploadMutation.isError || customError || clearIndexMutation.isError) && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" aria-hidden="true" />
              <AlertTitle>操作失败</AlertTitle>
              <AlertDescription className="text-sm">
                {customError ||
                  (uploadMutation.error instanceof Error
                    ? uploadMutation.error.message
                    : clearIndexMutation.error instanceof Error
                    ? clearIndexMutation.error.message
                    : "请重试，或检查后端 / 存储服务是否就绪。")}
              </AlertDescription>
            </Alert>
          )}

          <div className="flex flex-wrap items-center gap-2 text-xs text-[#5f3c86]">
            <span className="inline-flex items-center gap-1 rounded-full border border-[#cdb6f2] px-2 py-1 text-[#2b174d]">
              <FileUp className="h-3 w-3" aria-hidden="true" />
              支持拖拽
            </span>
            <span>上传成功后将自动刷新索引状态。</span>
          </div>
        </div>
      </Card>

      {/* 已上传文件列表 */}
      {allUploadedFiles.length > 0 && (
        <Card
          title="已上传文件"
          extra={
            <Badge variant="secondary" className="glass-effect flex items-center gap-1 text-white">
              <History className="h-3.5 w-3.5" />
              {allUploadedFiles.length}
            </Badge>
          }
        >
          <div className="max-h-96 space-y-2 overflow-y-auto">
            {allUploadedFiles.map((item, index) => (
              <div
                key={`${item.filename}-${item.chunks}-${index}`}
                className="glass-effect flex items-center justify-between gap-4 rounded-2xl border border-white/20 p-4 text-sm text-white/90"
              >
                <div className="min-w-0 flex-1 text-left">
                  <p className="truncate font-medium text-white">
                    {item.filename}
                  </p>
                  <p className="mt-1 text-xs text-white/70">
                    {item.chunks} 个切片 · 上传于 {new Date().toLocaleString()}
                  </p>
                </div>
                <Badge variant="secondary" className="glass-effect text-xs text-white">
                  {item.chunks} 切片
                </Badge>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}
