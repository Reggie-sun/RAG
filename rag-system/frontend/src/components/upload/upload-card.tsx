import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  Check,
  FileUp,
  Loader2,
  UploadCloud,
} from "lucide-react";
import {
  ChangeEvent,
  DragEvent,
  useCallback,
  useRef,
  useState,
} from "react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../ui/card";
import { Label } from "../ui/label";
import { Progress } from "../ui/progress";
import { Alert, AlertDescription, AlertTitle } from "../ui/alert";
import { uploadDocuments } from "../../services/api";
import type { UploadSummary } from "../../types/api";

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

interface UploadCardProps {
  onUploaded?: () => void;
}

const MAX_FILES_PER_BATCH = 3;

export function UploadCard({ onUploaded }: UploadCardProps) {
  const [progress, setProgress] = useState<number>(0);
  const [isDragActive, setIsDragActive] = useState(false);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [customError, setCustomError] = useState<string | null>(null);
  const [recentUploads, setRecentUploads] = useState<UploadSummary[]>([]);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const queryClient = useQueryClient();

  const uploadMutation = useMutation({
    mutationFn: (files: File[]) => uploadDocuments(files, setProgress),
    onSuccess: (data) => {
      setSuccessMessage(`已索引 ${data.processed.length} 个文件`);
      setRecentUploads(data.processed);
      setCustomError(null);
      queryClient.invalidateQueries({ queryKey: ["index-status"] });
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

  const resetDragState = useCallback(() => setIsDragActive(false), []);

  const handleFiles = useCallback(
    (files: FileList | null) => {
      if (!files || files.length === 0) return;

      const fileArray = Array.from(files).slice(0, MAX_FILES_PER_BATCH);
      setRecentUploads([]);
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

  return (
    <Card aria-live="polite">
      <CardHeader className="space-y-2">
        <CardTitle>上传新文档</CardTitle>
        <CardDescription>
          支持 PDF、TXT、DOCX 以及常见图片格式，上传后自动执行拆分与向量化。
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
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
          className={`flex cursor-pointer flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border bg-background/70 p-6 text-center transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background ${isDragActive ? "border-primary bg-primary/5" : ""}`}
          aria-label="拖拽或点击上传文件"
        >
          <UploadCloud className="h-8 w-8 text-muted-foreground" />
          <div className="space-y-1">
            <p className="text-sm font-medium">
              拖拽文件到此处，或
              <button
                type="button"
                onClick={(event) => {
                  event.preventDefault();
                  triggerFileSelect();
                }}
                className="ml-1 underline decoration-primary decoration-dashed underline-offset-4"
              >
                选择文件
              </button>
            </p>
            <p className="text-xs text-muted-foreground">
              支持 PDF / TXT / DOCX / ODT / PNG / JPG / BMP / TIFF / WEBP，单次最多 {MAX_FILES_PER_BATCH} 个文件
            </p>
          </div>
        </Label>

        {isUploading && (
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              文档上传中，请勿关闭页面…
            </div>
            <Progress value={progress} className="h-2" />
          </div>
        )}

        {uploadMutation.isSuccess && successMessage && (
          <Alert variant="success">
            <Check className="h-4 w-4" aria-hidden="true" />
            <AlertTitle>Indexed</AlertTitle>
            <AlertDescription className="text-sm text-emerald-600 dark:text-emerald-400">
              {successMessage}
            </AlertDescription>
          </Alert>
        )}

        {(uploadMutation.isError || customError) && (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" aria-hidden="true" />
            <AlertTitle>上传失败</AlertTitle>
            <AlertDescription className="text-sm">
              {customError ??
                (uploadMutation.error instanceof Error
                  ? uploadMutation.error.message
                  : "请重试，或检查后端 / 存储服务是否就绪。")}
            </AlertDescription>
          </Alert>
        )}

        {recentUploads.length > 0 && (
          <div className="space-y-2">
            <p className="text-sm font-medium">本次上传文件</p>
            <ul className="space-y-1 rounded-lg border border-border bg-muted/40 p-3 text-sm text-muted-foreground">
              {recentUploads.map((item) => (
                <li
                  key={`${item.filename}-${item.chunks}`}
                  className="flex items-center justify-between gap-3"
                >
                  <span className="truncate" title={item.filename}>
                    {item.filename}
                  </span>
                  <span className="text-xs text-emerald-600 dark:text-emerald-400">
                    {item.chunks} 个切片
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <span className="inline-flex items-center gap-1 rounded-full border border-border px-2 py-1">
            <FileUp className="h-3 w-3" aria-hidden="true" />
            支持拖拽
          </span>
          <span>上传成功后将自动刷新索引状态。</span>
        </div>
      </CardContent>
    </Card>
  );
}
