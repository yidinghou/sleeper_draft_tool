const API_BASE = "https://api.sleeper.app/v1";

export interface SleeperPlayer {
  player_id: string;
  first_name: string;
  last_name: string;
  full_name?: string;
  position: string;
  team: string | null;
  status: string;
  active?: boolean;
}

export interface SleeperProjection {
  player_id: string;
  pts_ppr?: number;
  pts_half_ppr?: number;
  pts_std?: number;
  adp_2qb?: number;
}

export interface DraftPick {
  draft_id: string;
  draft_slot: number;
  pick_no: number;
  round: number;
  picked_by: string;
  roster_id: number;
  player_id: string;
  is_keeper: boolean;
  metadata: {
    amount: string;
    player_id: string;
    position: string;
    team: string;
    first_name: string;
    last_name: string;
    [key: string]: unknown;
  };
}

export interface Draft {
  draft_id: string;
  league_id: string;
  season: string;
  type: string | null;
  status: string;
  settings: Record<string, unknown>;
  draft_order: string[] | null;
  metadata: {
    nominated_player_id?: string;
    nominating_slot?: string;
    highest_offer?: string;
    offering_slot?: string;
    last_action_at?: string;
    [key: string]: unknown;
  };
}

export interface Nomination {
  playerId: string | null;
  nominatingSlot: number | null;
  highestOffer: number | null;
  offeringSlot: number | null;
}

/** Cache-buster: Sleeper's CDN caches aggressively, so every request gets a unique query param. */
export function cacheBustedUrl(path: string, now: () => number = Date.now): string {
  const separator = path.includes("?") ? "&" : "?";
  return `${API_BASE}${path}${separator}_cb=${now()}`;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(cacheBustedUrl(path), { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`Sleeper API ${path} failed: ${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export async function fetchPlayers(): Promise<Record<string, SleeperPlayer>> {
  return get<Record<string, SleeperPlayer>>("/players/nfl");
}

export async function fetchSeasonProjections(
  season: number,
): Promise<Record<string, SleeperProjection>> {
  return get<Record<string, SleeperProjection>>(`/projections/nfl/regular/${season}`);
}

export async function fetchWeeklyProjections(
  season: number,
  week: number,
): Promise<Record<string, SleeperProjection>> {
  return get<Record<string, SleeperProjection>>(`/projections/nfl/regular/${season}/${week}`);
}

export async function fetchDraft(draftId: string): Promise<Draft> {
  return get<Draft>(`/draft/${draftId}`);
}

export async function fetchDraftPicks(draftId: string): Promise<DraftPick[]> {
  return get<DraftPick[]>(`/draft/${draftId}/picks`);
}

/** Fingerprint of a draft's live-relevant metadata, used to decide whether to refetch picks. */
export function draftFingerprint(draft: Draft): string {
  const m = draft.metadata;
  return [
    draft.status,
    m.nominated_player_id ?? "",
    m.highest_offer ?? "",
    m.offering_slot ?? "",
    m.last_action_at ?? "",
  ].join("|");
}

export function parseNomination(draft: Draft): Nomination {
  const m = draft.metadata;
  return {
    playerId: m.nominated_player_id ?? null,
    nominatingSlot: m.nominating_slot != null ? Number(m.nominating_slot) : null,
    highestOffer: m.highest_offer != null ? Number(m.highest_offer) : null,
    offeringSlot: m.offering_slot != null ? Number(m.offering_slot) : null,
  };
}

export function sleeperPlayerFullName(p: SleeperPlayer): string {
  return p.full_name ?? `${p.first_name} ${p.last_name}`;
}
