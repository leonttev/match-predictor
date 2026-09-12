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

export type Tier = "tier1" | "tier2" | "tier3" | "unknown";

/** Teams are ranked tier-first, so a tier2 team never sits above a tier1 one. */
export const TIER_RANK: Record<Tier, number> = {
  tier1: 1,
  tier2: 2,
  tier3: 3,
  unknown: 4,
};

export const TIER_LABEL: Record<Tier, string> = {
  tier1: "Tier 1",
  tier2: "Tier 2",
  tier3: "Tier 3",
  unknown: "—",
};

export function tierRank(tier: string): number {
  return TIER_RANK[tier as Tier] ?? 4;
}

export function tierLabel(tier: string): string {
  return TIER_LABEL[tier as Tier] ?? "—";
}

export interface Team {
  id: number;
  opendota_team_id: number;
  name: string;
  tag: string | null;
  rating: number;
  recent_form: number;
  tier: string;
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
  league_tier: string | null;
}

export interface LoginResponse {
  status: "ok" | "2fa_required";
  token: string;
}

export interface PredictResponse {
  team_a: { id: number; name: string; tier: string };
  team_b: { id: number; name: string; tier: string };
  team_a_win_prob: number;
  elo_component: number;
  form_component: number;
  tier_adjustment: number;
  prediction_id: number;
}

export interface RosterPlayer {
  name: string;
  games_played: number;
}

export interface Roster {
  team_id: number;
  team_name: string;
  players: RosterPlayer[];
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

  me: (token: string) =>
    request<{ username: string; totp_enabled: boolean }>("/auth/me", { token }),

  listTeams: (token: string) => request<Team[]>("/teams", { token }),

  getRoster: (token: string, teamId: number) =>
    request<Roster>(`/teams/${teamId}/roster`, { token }),

  listMatches: (token: string, limit = 30, tier?: string) =>
    request<Match[]>(`/matches?limit=${limit}${tier ? `&tier=${tier}` : ""}`, { token }),

  predict: (token: string, teamAId: number, teamBId: number) =>
    request<PredictResponse>("/predict", {
      method: "POST",
      token,
      body: { team_a_id: teamAId, team_b_id: teamBId },
    }),

  runIngestion: (token: string) =>
    request<{
      teams_ingested: number;
      matches_ingested: number;
      tier1_matches: number;
      ratings_updated: number;
    }>("/ingest/run",
      { method: "POST", token },
    ),
};
