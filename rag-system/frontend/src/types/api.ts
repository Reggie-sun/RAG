export interface IndexStatus {
  documents: number;
  chunks: number;
  updated_at: string;
}

export interface UploadSummary {
  filename: string;
  chunks: number;
  size?: number;
  lastModified?: number;
  uploadedAt?: number;
}

export interface UploadResponse {
  processed: UploadSummary[];
}

export type SearchMode = "doc" | "general" | "chitchat" | "guidance" | "hybrid" | "multi_topic";

export type SourceType = "document" | "web" | "knowledge_base" | "code";

export interface Citation {
  source: string;
  source_type?: SourceType;
  page?: number | null;
  snippet?: string | null;
  score?: number | null;
  title?: string | null;
  url?: string | null;
  published_date?: string | null;
  confidence?: "high" | "medium" | "low";
  file_path?: string | null;
  retrieved_at?: string | null;
  position?: number | null;
}

export interface IntentAnalysis {
  question_type: "fact" | "how_to" | "comparison" | "decision" | "general";
  answering_mode: "general_only" | "document_first" | "hybrid";
  confidence: number;
  requires_web_search: boolean;
  time_sensitivity: number;
  complexity_score: number;
  reasoning?: string;
}

export interface SearchDiagnostics {
  intent_analysis?: IntentAnalysis;
  web_search_used?: boolean;
  web_hits?: number;
  retrieval_time?: number;
  generation_time?: number;
  topics?: Record<string, unknown>;
  errors?: string[];
}

export interface SourceStats {
  total_citations: number;
  by_type: Record<SourceType, number>;
  confidence_distribution: {
    high: number;
    medium: number;
    low: number;
  };
  average_score: number;
  unique_sources: number;
}

export interface AnswerMeta {
  strategy: string;
  answering_mode?: string;
  question_type?: string;
  time_sensitivity?: number;
  confidence?: number;
  multi_topic?: boolean;
  topics?: string[];
  truncated_topics?: boolean;
  web_search_used?: boolean;
  source_counts?: {
    documents: number;
    web: number;
  };
  modules?: {
    doc_only?: boolean;
    allow_web?: boolean;
    stacked?: boolean;
  };
  feedback_history?: string;
}

export interface SearchResponse {
  answer: string;
  mode: SearchMode;
  citations: Citation[];
  session_id?: string;
  suggestions?: string[];
  sources?: Citation[];  // 所有来源，包括网络搜索
  diagnostics?: SearchDiagnostics;
  source_stats?: SourceStats;
  multi_topics?: string[];  // 多主题的主题列表
  meta?: AnswerMeta;
}

export interface AskResponse {
  task_id: string | null;
  session_id?: string;
  result?: SearchResponse;
}

export type TaskStatus = "pending" | "started" | "success" | "failure" | string;

export interface TaskResult {
  status: TaskStatus;
  result?: (SearchResponse & { question?: string }) | null;
  error?: string;
}
