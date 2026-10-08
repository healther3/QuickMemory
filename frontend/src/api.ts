import { useCallback, useEffect, useRef, useState } from "react";
import type { components } from "./generated/api-schema";
// Generated OpenAPI owns all persisted API shapes. Narrow the two generic
// dictionaries whose semantic definitions live in docs/CORE_CONTRACT.md.
type Schemas = components["schemas"];
export type Named = Schemas["NamedOutput"];
export type Tag = Schemas["TagOutput"];
export type Folder = Schemas["FolderOutput"];
export type Card = Schemas["CardOutput"];
export type CardInput = Required<Schemas["CardInput"]>;
export type Question = Schemas["QuestionResponse"];
export type Feedback = {
  correct_parts: string[];
  wrong_parts: string[];
  uncertain_parts: string[];
  error_types: string[];
};
export type Judge = Schemas["JudgeResponse"];
export type Answer = Omit<Schemas["AnswerResponse"], "merged_feedback"> & {
  merged_feedback: Partial<Feedback> | null;
};
export type Exam<T = Question> = Omit<Schemas["ExamResponse"], "answers"> & {
  answers: T[];
};
export type CardStats = Schemas["CardStats"];
export type Stats = Schemas["StatsResponse"];
export type CardHistory = Omit<Schemas["CardHistory"], "answers"> & {
  answers: Answer[];
};
export type Settings = Omit<
  Schemas["SettingsView"],
  "judge_count" | "json_mode"
> & { judge_count: 2 | 3; json_mode: "auto" | "on" | "off" };
export type Provider = {
  id: string;
  name: string;
  base_url: string;
  suggested_model: string;
};
export type Precheck = Schemas["PrecheckFeedback"];
export type ImportInput = Required<
  Omit<Schemas["ImportRequest"], "filename" | "folder_name">
> & { filename: string; folder_name: string };
export type ImportReport = Schemas["ImportReport"] & { folder_id?: number };

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init.headers },
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError")
      throw error;
    throw new ApiError("暂时无法连接本地服务，请确认服务已启动后重试。", 0);
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = body.detail;
    throw new ApiError(
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((item: { msg: string }) => item.msg).join("；")
          : "请求失败，请稍后重试。",
      response.status,
    );
  }
  if (response.status === 204) return undefined as T;
  return response.json();
}
export const send = <T>(path: string, body?: unknown, method = "POST") =>
  api<T>(path, {
    method,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
export const message = (error: unknown) =>
  error instanceof Error ? error.message : "操作失败，请重试。";
export function useLoad<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(true),
    [revision, setRevision] = useState(0);
  const reload = useCallback(() => setRevision((n) => n + 1), []);
  const current = useRef(path);
  current.current = path;
  useEffect(() => {
    if (!path) {
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError("");
    api<T>(path, { signal: controller.signal })
      .then((value) => {
        if (!controller.signal.aborted) setData(value);
      })
      .catch((error) => {
        if (!controller.signal.aborted) setError(message(error));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [path, revision]);
  return { data, setData, error, loading, reload };
}
export const score = (value: number | null | undefined) =>
  value == null ? "—" : Number(value.toFixed(1)).toString();
export const duration = (value: number | null | undefined) =>
  value == null
    ? "—"
    : value < 60000
      ? `${Math.round(value / 1000)} 秒`
      : `${Math.floor(value / 60000)} 分 ${Math.round((value % 60000) / 1000)} 秒`;
export const date = (value: string) =>
  new Date(value).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
