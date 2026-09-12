const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function request<T>(
  path: string,
  options: { method?: string; body?: unknown; token?: string | null } = {},
): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (options.token) headers.Authorization = `Bearer ${options.token}`;

  const res = await fetch(`${API_BASE}${path}`, {
    method: options.method ?? "GET",
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });

  if (!res.ok) {
    const text = await res.text();
    throw new ApiError(text || res.statusText, res.status);
  }
  return res.json() as Promise<T>;
}

export interface Team {
  id: number;
  opendota_team_id: number;
  name: string;
  tag: string | null;
  rating: number;
  recent_form: number;
}

export interface Match {
  id: number;
  opendota_match_id: number;
  radiant_team_id: number;
  dire_team_id: number;
  radiant_team_name: string;
  dire_team_name: string;
  radiant_win: boolean;
  start_time: number;
  league_name: string | null;
}

export interface LoginResponse {
  status: "ok" | "2fa_required";
  token: string;
}

export interface PredictResponse {
  team_a: { id: number; name: string };
  team_b: { id: number; name: string };
  team_a_win_prob: number;
  elo_component: number;
  form_component: number;
  prediction_id: number;
}

export const api = {
  register: (username: string, email: string, password: string) =>
    request<{ id: number; username: string }>("/auth/register", {
      method: "POST",
      body: { username, email, password },
    }),

  login: (username: string, password: string) =>
    request<LoginResponse>("/auth/login", { method: "POST", body: { username, password } }),

  loginWith2fa: (pendingToken: string, code: string) =>
    request<LoginResponse>("/auth/2fa/login", {
      method: "POST",
      body: { pending_token: pendingToken, code },
    }),

  setup2fa: (token: string) =>
    request<{ secret: string; provisioning_uri: string }>("/auth/2fa/setup", {
      method: "POST",
      token,
    }),

  enable2fa: (token: string, code: string) =>
    request<{ status: string }>("/auth/2fa/enable", { method: "POST", token, body: { code } }),

  listTeams: (token: string) => request<Team[]>("/teams", { token }),

  listMatches: (token: string, limit = 30) =>
    request<Match[]>(`/matches?limit=${limit}`, { token }),

  predict: (token: string, teamAId: number, teamBId: number) =>
    request<PredictResponse>("/predict", {
      method: "POST",
      token,
      body: { team_a_id: teamAId, team_b_id: teamBId },
    }),

  runIngestion: (token: string) =>
    request<{ teams_ingested: number; matches_ingested: number; ratings_updated: number }>(
      "/ingest/run",
      { method: "POST", token },
    ),
};
