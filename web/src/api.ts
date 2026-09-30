export type Format = {
  id: string;
  quality: string;
  width: number | null;
  height: number | null;
  ext: string;
  size_bytes: number | null;
  size_kind: string;
  has_audio: boolean | null;
  watermark: "absent" | "present" | "unknown";
  requires_mux: boolean;
  codec: string;
};
export type Media = {
  id: string;
  title: string;
  author: string;
  platform: string;
  duration: number | null;
  cover: boolean;
  formats: Format[];
  adapter: string;
  resolved_at: number;
};
export type Job = {
  id: string;
  kind: "resolve" | "download";
  platform: string;
  status: "queued" | "running" | "ready" | "failed" | "cancelled";
  stage: string;
  created_at: number;
  updated_at: number;
  version: number;
  result: null | {
    media_id?: string;
    artifact_id?: string;
    filename?: string;
    size_bytes?: number;
    expires_at?: number;
  };
  error: null | { code: string; message: string; retryable: boolean };
  progress: {
    received_bytes?: number;
    total_bytes?: number | null;
    speed_bps?: number;
  };
  title?: string;
  quality?: string;
};
export type Platform = {
  id: string;
  name: string;
  status: string;
  label: string;
  description: string;
};
export type SessionInfo = {
  csrf_token: string;
  sample_url: string;
  limits: { max_bytes: number; max_duration: number };
  version: string;
};
let csrf = "";
export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch("/api/v1" + path, {
    credentials: "same-origin",
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.method && options.method !== "GET"
        ? { "X-CSRF-Token": csrf }
        : {}),
      ...options.headers,
    },
  });
  const data = await response.json();
  if (!response.ok)
    throw new Error(
      data.error?.message ||
        (response.status === 422
          ? "请求参数无效，请重新选择。"
          : "暂时无法连接服务，请稍后再试。"),
    );
  return data;
}
export async function bootstrap() {
  const data = await api<SessionInfo>("/session");
  csrf = data.csrf_token;
  return data;
}
export const post = <T>(path: string, body: unknown = {}) =>
  api<T>(path, {
    method: "POST",
    body: JSON.stringify(body),
    headers: { "Idempotency-Key": crypto.randomUUID() },
  });
export const terminal = (job?: Job | null) =>
  !!job && ["ready", "failed", "cancelled"].includes(job.status);
export const names: Record<string, string> = {
  douyin: "抖音",
  kuaishou: "快手",
  xiaohongshu: "小红书",
  bilibili: "哔哩哔哩",
  youtube: "YouTube",
  tiktok: "TikTok",
  instagram: "Instagram",
  twitter: "X",
  direct: "视频直链",
};
export const stages: Record<string, string> = {
  queued: "等待处理",
  resolving: "正在解析视频",
  refreshing: "正在获取最新视频源",
  fetching: "正在下载视频",
  muxing: "正在合并音视频",
  verifying: "正在检查文件",
  ready: "文件已就绪",
  failed: "未能完成",
  cancelled: "已取消",
};
export function bytes(value?: number | null) {
  if (value == null) return "大小待确认";
  if (value >= 1024 ** 3) return (value / 1024 ** 3).toFixed(2) + " GB";
  return (value / 1024 ** 2).toFixed(1) + " MB";
}
export function duration(value: number | null) {
  if (value == null) return "时长待确认";
  const m = Math.floor(value / 60);
  return `${m}:${String(Math.floor(value % 60)).padStart(2, "0")}`;
}
