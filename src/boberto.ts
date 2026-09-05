import { sleeperPlayerFullName, type SleeperPlayer } from "./sleeper.ts";

const API_BASE = "https://www.boberto.app/api";

/** One projected stat line. Keys present depend on position; see STAT_COLUMNS. */
export type BobertoStats = Record<string, number>;

export interface BobertoProjection {
  playerName: string;
  position: string;
  team: string | null;
  bye?: number;
  stats: BobertoStats;
}

export interface BobertoAavEntry {
  name: string;
  team: string | null;
  position: string;
  aav: number;
}

export interface BobertoAav {
  sources: Record<string, BobertoAavEntry[]>;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) {
    throw new Error(`Boberto API ${path} failed: ${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export async function fetchBobertoProjections(season: number): Promise<BobertoProjection[]> {
  return get<BobertoProjection[]>(`/fantasypros/projections?season=${season}`);
}

export async function fetchBobertoAav(season: number): Promise<BobertoAav> {
  return get<BobertoAav>(`/market/aav?season=${season}&source=all`);
}

const NAME_SUFFIXES = new Set(["jr", "sr", "ii", "iii", "iv", "v"]);

/**
 * Nicknames a feed uses where Sleeper carries the legal name. Both sides are in
 * normalized form. Applying these inside normalizeName means the alias also runs
 * over the Sleeper side of the index, so an alias can only ever merge two spellings
 * of one player — it can't point at a player who isn't there.
 *
 * To extend: run `npm run export:boberto` and add a line for anything it prints as
 * unmatched. Keep it exact; a fuzzy matcher would trade these few known misses for
 * silent wrong matches.
 */
const NAME_ALIASES: Record<string, string> = {
  "hollywood brown": "marquise brown",
  "bam knight": "zonovan knight",
};

/** "Amon-Ra St. Brown" -> "amon ra st brown", "Marvin Harrison Jr." -> "marvin harrison". */
export function normalizeName(name: string): string {
  const cleaned = name
    .toLowerCase()
    .replace(/[.']/g, "")
    .replace(/-/g, " ")
    .replace(/[^a-z ]/g, "");
  const normalized = cleaned
    .split(/\s+/)
    .filter((token) => token && !NAME_SUFFIXES.has(token))
    .join(" ");
  return NAME_ALIASES[normalized] ?? normalized;
}

export interface PlayerIndex {
  byNamePosition: Map<string, SleeperPlayer[]>;
  byName: Map<string, SleeperPlayer[]>;
  defenseByTeam: Map<string, SleeperPlayer>;
}

export function buildPlayerIndex(players: Record<string, SleeperPlayer>): PlayerIndex {
  const index: PlayerIndex = { byNamePosition: new Map(), byName: new Map(), defenseByTeam: new Map() };
  for (const player of Object.values(players)) {
    if (!player.position) continue;
    if (player.position === "DEF" && player.team) index.defenseByTeam.set(player.team, player);
    const name = normalizeName(sleeperPlayerFullName(player));
    if (!name) continue;
    push(index.byName, name, player);
    push(index.byNamePosition, `${name}|${player.position}`, player);
  }
  return index;
}

function push(map: Map<string, SleeperPlayer[]>, key: string, player: SleeperPlayer): void {
  const bucket = map.get(key);
  if (bucket) bucket.push(player);
  else map.set(key, [player]);
}

/** Narrow a name bucket to one player using team, then active status. */
function resolve(candidates: SleeperPlayer[], team: string | null): SleeperPlayer | null {
  if (candidates.length === 1) return candidates[0];
  if (candidates.length === 0) return null;
  const sameTeam = candidates.filter((p) => p.team === team);
  if (sameTeam.length === 1) return sameTeam[0];
  const active = (sameTeam.length ? sameTeam : candidates).filter((p) => p.active !== false);
  return active.length === 1 ? active[0] : null;
}

/** Feed team abbreviations that differ from Sleeper's. "FA" means no team at all. */
const TEAM_ALIASES: Record<string, string | null> = { ARZ: "ARI", JAC: "JAX", LA: "LAR", FA: null };

export function normalizeTeam(team: string | null | undefined): string | null {
  if (!team) return null;
  return team in TEAM_ALIASES ? TEAM_ALIASES[team] : team;
}

export interface FeedPlayer {
  name: string;
  position: string;
  team: string | null;
}

/**
 * Resolve a boberto feed row to a Sleeper player. DEF is keyed by team abbreviation
 * (Sleeper's DEF player_id *is* the abbreviation), which covers every naming style
 * the feeds use for defenses: "Texans D/ST", "Rams", "New York Jets".
 */
export function matchSleeperPlayer(index: PlayerIndex, feed: FeedPlayer): SleeperPlayer | null {
  const team = normalizeTeam(feed.team);
  if (feed.position === "DEF") {
    return (team && index.defenseByTeam.get(team)) || null;
  }
  const name = normalizeName(feed.name);
  return (
    resolve(index.byNamePosition.get(`${name}|${feed.position}`) ?? [], team) ??
    // Fullbacks and other position disagreements: fall back to name alone.
    resolve(index.byName.get(name) ?? [], team)
  );
}
