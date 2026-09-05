/**
 * The Sleeper draft board, as a CSV — rank, bye and the board's own points
 * projection, for every player Sleeper projects.
 *
 * This file used to be scraped by hand from a logged-in browser session, on the
 * belief that the board's numbers were computed client-side and off the API
 * (see docs/sleeper-api.md, "Auction value"). Reading the draft board's React
 * state showed otherwise: the rows it renders come straight from the public
 * projections feed, and the one number it really does compute is `rank`, which
 * is nothing more than the feed ordered by `adp_half_ppr` — verified against
 * the live board, 18 ranks including the gaps that drafted players leave.
 *
 * So the whole file is derivable, and this replaces the scrape:
 *
 *   rank   <- position in adp_half_ppr order (the board's own ordering)
 *   bye    <- the week missing from a team's schedule
 *   pts    <- stats.pts_half_ppr, byte-identical to the board's PTS column
 *
 * `sleeper_proj_dollar` is the exception and is genuinely browser-only: it is
 * an auction number the board derives client-side, and a snake draft has none.
 * Existing values are carried over from the previous CSV rather than dropped,
 * so re-running this never destroys an auction snapshot.
 */
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";

/** The projections feed the draft board itself renders. Not on /v1. */
const PROJECTIONS_BASE = "https://api.sleeper.com/projections/nfl";
const SCHEDULE_BASE = "https://api.sleeper.app/schedule/nfl/regular";

const POSITIONS = ["QB", "RB", "WR", "TE", "K", "DEF"];

/** Regular-season weeks. A team plays all but one of them; the gap is its bye. */
const WEEKS = 18;

interface ProjectionRow {
  player_id: string;
  team: string | null;
  stats: Record<string, number | undefined> | null;
}

interface Game {
  week: number;
  home: string;
  away: string;
}

async function get<T>(url: string): Promise<T> {
  const res = await fetch(`${url}${url.includes("?") ? "&" : "?"}_cb=${Date.now()}`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`${url} failed: ${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

/** Bye week per team: the one regular-season week it has no game. */
export function byeWeeks(schedule: Game[]): Map<string, number> {
  const played = new Map<string, Set<number>>();
  for (const game of schedule) {
    for (const team of [game.home, game.away]) {
      if (!played.has(team)) played.set(team, new Set());
      played.get(team)!.add(game.week);
    }
  }
  const byes = new Map<string, number>();
  for (const [team, weeks] of played) {
    const missing = [];
    for (let w = 1; w <= WEEKS; w++) if (!weeks.has(w)) missing.push(w);
    // Exactly one missing week is the bye. Anything else means the schedule is
    // incomplete (a season not fully published yet), and guessing which gap is
    // the real bye would put a wrong number on every player of that team.
    if (missing.length === 1) byes.set(team, missing[0]);
  }
  return byes;
}

/** The board's rank: the feed in `adp_half_ppr` order, unranked players last.
 *
 * Ranks are assigned across *every* row, including the ones with no points
 * projection, which is why the ranks that survive into the CSV have gaps in
 * them — the same gaps the live board shows.
 */
export function boardRanks(rows: ProjectionRow[]): Map<string, number> {
  const adp = (r: ProjectionRow) => r.stats?.adp_half_ppr ?? Number.POSITIVE_INFINITY;
  const ordered = [...rows].sort((a, b) => adp(a) - adp(b));
  return new Map(ordered.map((r, i) => [r.player_id, i + 1]));
}

/** Auction dollars from the previous CSV, so a re-run never drops them. */
function priorDollars(csvPath: string): Map<string, string> {
  const dollars = new Map<string, string>();
  if (!existsSync(csvPath)) return dollars;
  const lines = readFileSync(csvPath, "utf-8").trim().split("\n");
  for (const line of lines.slice(1)) {
    const [playerId, , , dollar] = line.split(",");
    if (dollar) dollars.set(playerId, dollar);
  }
  return dollars;
}

async function main() {
  const season = Number(process.argv[2] ?? 2026);
  const query = POSITIONS.map((p) => `position[]=${p}`).join("&");
  const [rows, schedule] = await Promise.all([
    get<ProjectionRow[]>(`${PROJECTIONS_BASE}/${season}?season_type=regular&${query}`),
    get<Game[]>(`${SCHEDULE_BASE}/${season}`),
  ]);

  const byes = byeWeeks(schedule);
  const ranks = boardRanks(rows);
  const outPath = path.join("data", `sleeper-board-${season}.csv`);
  const dollars = priorDollars(outPath);

  const projected = rows
    .filter((r) => r.stats?.pts_half_ppr !== undefined)
    .sort((a, b) => ranks.get(a.player_id)! - ranks.get(b.player_id)!);

  const lines = ["player_id,sleeper_rank,bye_week,sleeper_proj_dollar,sleeper_board_pts_half_ppr"];
  for (const row of projected) {
    lines.push(
      [
        row.player_id,
        ranks.get(row.player_id),
        (row.team && byes.get(row.team)) ?? "",
        dollars.get(row.player_id) ?? "",
        row.stats!.pts_half_ppr,
      ].join(","),
    );
  }

  mkdirSync("data", { recursive: true });
  writeFileSync(outPath, lines.join("\n") + "\n");
  console.log(
    `Wrote ${projected.length} rows to ${outPath} ` +
      `(${byes.size} teams' byes, ${dollars.size} auction values carried over).`,
  );
}

if (import.meta.filename === process.argv[1]) {
  await main();
}
