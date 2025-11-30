import axios from "axios";
import type {
  AskResponse,
  IndexStatus,
  SearchResponse,
  TaskResult,
  UploadResponse,
} from "../types/api";
import { getSessionId, setSessionId } from "../lib/session";

const GPU_API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";
const CPU_API_BASE =
  import.meta.env.VITE_CPU_API_BASE_URL ?? GPU_API_BASE;

const gpuClient = axios.create({
  baseURL: GPU_API_BASE,
  timeout: 90_000,
});

const cpuClient = axios.create({
  baseURL: CPU_API_BASE,
  timeout: 90_000,
});

export interface SearchRequestPayload {
  query: string;
  docOnly?: boolean;
  allowWeb?: boolean;
  webMode?: string;
  rerank?: boolean;
  topK?: number;
  feedback?: string;
  feedbackTags?: string[];
}

export function getIndexStatus() {
  // 优先取 GPU 节点的索引状态，失败再回退 CPU，避免上传走 GPU 时前端显示 0
  return gpuClient
    .get<IndexStatus>("/api/index/status")
    .then((res) => res.data)
    .catch(() =>
      cpuClient.get<IndexStatus>("/api/index/status").then((res) => res.data),
    );
}

export function searchDocuments(payload: SearchRequestPayload) {
  const sessionId = getSessionId();
  const body = {
    query: payload.query,
    session_id: sessionId,
    doc_only: payload.docOnly,
    allow_web: payload.allowWeb,
    web_mode: payload.webMode,
    use_rerank: payload.rerank,
    top_k: payload.topK,
    feedback: payload.feedback,
    feedback_tags: payload.feedbackTags,
  };

  return gpuClient
    .post<SearchResponse>("/api/search", body)
    .then((res) => {
      const data = res.data;
      if (data?.session_id) {
        setSessionId(data.session_id);
      }
      return data;
    });
}

export function uploadDocuments(
  files: File[],
  onProgress?: (progress: number) => void,
) {
  const body = new FormData();
  files.forEach((file) => {
    body.append("files", file);
  });

  return gpuClient
    .post<UploadResponse>("/api/upload", body, {
      headers: { "Content-Type": "multipart/form-data" },
      timeout: 300_000, // 上传可能较大，单独放宽超时时间
      onUploadProgress(event) {
        if (!event.total) return;
        const percent = Math.round((event.loaded / event.total) * 100);
        onProgress?.(percent);
      },
    })
    .then((res) => res.data);
}

export function askAsync(payload: SearchRequestPayload) {
  const sessionId = getSessionId();
  const body = {
    query: payload.query,
    session_id: sessionId,
    doc_only: payload.docOnly,
    allow_web: payload.allowWeb,
    web_mode: payload.webMode,
    use_rerank: payload.rerank,
    top_k: payload.topK,
    feedback: payload.feedback,
    feedback_tags: payload.feedbackTags,
  };

  return gpuClient
    .post<AskResponse>("/api/ask", body)
    .then((res) => {
      const data = res.data;
      if (data?.session_id) {
        setSessionId(data.session_id);
      }
      const sessionFromResult = data.result?.session_id;
      if (sessionFromResult) {
        setSessionId(sessionFromResult);
      }
      return data;
    });
}

export function getTaskResult(taskId: string) {
  return gpuClient
    .get<TaskResult>(`/api/result/${taskId}`)
    .then((res) => {
      const data = res.data;
      const sessionFromResult = data.result?.session_id;
      if (sessionFromResult) {
        setSessionId(sessionFromResult);
      }
      return data;
    });
}

export async function clearIndex() {
  const [cpuResult, gpuResult] = await Promise.allSettled([
    cpuClient.delete<{ status: string; message: string }>("/api/index/clear"),
    gpuClient.delete<{ status: string; message: string }>("/api/index/clear"),
  ]);

  const extract = (
    result: PromiseSettledResult<{ data: { status: string; message: string } }>,
  ) => (result.status === "fulfilled" ? result.value.data : null);

  const cpuData = extract(cpuResult);
  const gpuData = extract(gpuResult);

  if (!cpuData && !gpuData) {
    const cpuError =
      cpuResult.status === "rejected" ? cpuResult.reason : null;
    const gpuError =
      gpuResult.status === "rejected" ? gpuResult.reason : null;
    const combined = [cpuError, gpuError].filter(Boolean).join(" | ");
    throw new Error(combined || "Failed to clear indexes on all servers");
  }

  const messageParts: string[] = [];
  if (cpuData) messageParts.push("CPU 节点");
  if (gpuData) messageParts.push("GPU 节点");

  return {
    status: "ok",
    message: `${messageParts.join(" / ")}索引已清空`,
  };
}
