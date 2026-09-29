export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type DashboardSummary = {users: number; critical: number; high: number; medium: number; low: number; average_score: number; last_sync_at: string | null};
export type UserSummary = {id: string; display_name: string; is_admin: boolean; is_mfa_registered: boolean; is_mfa_capable: boolean; entra_risk_level: string; score: number; level: string; calculated_at: string | null};
export type Risk = {id: string; user_id: string; score: number; level: string; calculated_at: string; model_version: string; factors: {name: string; contribution: number}[]; recommended_actions: string[]};
export type ModelInfo = {version: string; approved: boolean; feature_version: string; metrics: Record<string, unknown>};
export type SyncJob = {id: string; status: string; attempt: number; created_at: string; completed_at: string | null; next_attempt_at: string; error: string | null};
export type CursorPage<T> = {items: T[]; next_cursor: string | null};
export type Connection = {mode: "mock" | "real"; status: string; provider: string; scopes: string[]; updated_at: string | null};
export type Onboarding = {mode: "mock" | "real"; status?: string; url?: string};
export type MailEvent = {id: string; user_id: string; received_at: string; risk_probability: number; external_sender: boolean; recipient_count: number; has_attachments: boolean; importance: "low" | "normal" | "high"; authentication_results: Record<string, string>; reply_to_domain_mismatch: boolean; from_sender_mismatch: boolean; received_hops: number; sender_domain_hash: string};
export type RiskGraphNode = {id: string; kind: "employee" | "observation" | "feature" | "component"; label: string; status: "available" | "unavailable" | "insufficient_history"; value: number | string | boolean | null; observed_at: string | null; metadata: Record<string, unknown>};
export type RiskGraphEdge = {source: string; target: string; relation: "HAS_OBSERVATION" | "DERIVES" | "CONTRIBUTES_TO"};
export type UserRiskGraph = {user_id: string; feature_version: string; model_version: string; calculated_at: string; score: number | null; level: string; components: Record<string, number | null>; coverage: Record<string, "available" | "unavailable" | "insufficient_history">; nodes: RiskGraphNode[]; edges: RiskGraphEdge[]};

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function request<T>(path: string, token: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {"Content-Type": "application/json", Authorization: `Bearer ${token}`, ...init?.headers},
  });
  if (!response.ok) {
    const contentType = response.headers.get("content-type") ?? "";
    let message = `Request failed: ${response.status}`;
    if (contentType.includes("application/json")) {
      const payload = await response.json() as {message?: string; detail?: string};
      message = payload.message ?? payload.detail ?? message;
    } else {
      message = (await response.text()) || message;
    }
    throw new ApiError(message, response.status);
  }
  return response.json() as Promise<T>;
}
