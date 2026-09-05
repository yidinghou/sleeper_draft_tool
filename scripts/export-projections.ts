import { mkdirSync, existsSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import {
  fetchLeague,
  fetchPlayers,
  fetchSeasonProjections,
  fetchWeeklyProjections,
  scoreProjection,
  sleeperPlayerFullName,
  type SleeperPlayer,
} from "../src/sleeper.ts";

/** Weeks summed into the early-season points column. */
const EARLY_WEEKS = [1, 2, 3];

/** The snake keeper league, whose scoring the weekly columns are priced in.
 *
 * The auction league (1372724723108036608) scores offence identically -- 4
 * points a passing TD, half PPR -- and differs only in `fum` (-1 here, 0
 * there) plus kicker and defence rules, neither of which reaches these
 * columns: K and DEF are drafted by hand and excluded from the board.
 *
 * ponytail: one league's settings for both consumers, because today they agree
 * where it counts. Take a --league argument if they ever diverge on offence.
 */
const SCORING_LEAGUE_ID = "1386051970791378944";

interface BoardEntry {
  rank: number;
  bye: string;
  dollar: string;
  pts?: number;
}

function round(n: number | undefined): string {
  return n === undefined ? "" : (Math.round(n * 100) / 100).toString();
}

function csvCell(value: string): string {
  if (/[",\n]/.test(value)) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
}

function loadBoard(season: number): Map<string, BoardEntry> {
  const boardPath = path.join("data", `sleeper-board-${season}.csv`);
  const board = new Map<string, BoardEntry>();
  if (!existsSync(boardPath)) {
    console.warn(`No board CSV at ${boardPath} — rank/bye/dollar columns will be blank.`);
    return board;
  }
  const lines = readFileSync(boardPath, "utf-8").trim().split("\n");
  for (const line of lines.slice(1)) {
    const [playerId, rank, bye, dollar, pts] = line.split(",");
    board.set(playerId, { rank: Number(rank), bye, dollar, pts: pts ? Number(pts) : undefined });
  }
  return board;
}

async function main() {
  const season = Number(process.argv[2] ?? 2026);

  const [players, projections, weeklyProjections, league] = await Promise.all([
    fetchPlayers(),
    fetchSeasonProjections(season),
    Promise.all(EARLY_WEEKS.map((week) => fetchWeeklyProjections(season, week))),
    fetchLeague(SCORING_LEAGUE_ID),
  ]);
  const board = loadBoard(season);

  // Scored with the league's own rules rather than read off `pts_half_ppr`,
  // which pays 6 for a passing TD where these leagues pay 4 -- worth about
  // four points a game to every QB. The season column beside these comes from
  // the league's board and is already priced correctly, so taking Sleeper's
  // generic number here put two different scorings in one row.
  const scoring = league.scoring_settings;
  const earlyWeeksPts = new Map<string, number>();
  for (const weekProjections of weeklyProjections) {
    for (const [playerId, proj] of Object.entries(weekProjections)) {
      if (proj.pts_half_ppr === undefined) continue;  // not projected this week
      earlyWeeksPts.set(playerId, (earlyWeeksPts.get(playerId) ?? 0) + scoreProjection(proj, scoring));
    }
  }

  // Week 1 on its own. It is already in `weeklyProjections` -- the sum above
  // just throws the split away -- so this costs no extra request. Kept
  // separate from the three-week total because a player who ramps late and one
  // who produces immediately can share a wk1-3 number.
  const week1Pts = new Map<string, number>();
  for (const [playerId, proj] of Object.entries(weeklyProjections[EARLY_WEEKS.indexOf(1)] ?? {})) {
    if (proj.pts_half_ppr !== undefined) week1Pts.set(playerId, scoreProjection(proj, scoring));
  }

  const header = [
    "player_id",
    "player",
    "position",
    "team",
    "sleeper_rank",
    "bye_week",
    "sleeper_proj_dollar",
    "season_pts_half_ppr",
    "pts_source",
    // Named for the league, not for half-PPR: these are scored with the
    // league's settings, and `season_pts_half_ppr` beside them keeps its name
    // only because it is board-sourced and read by name all over the repo.
    "wk1_3_pts_league",
    "wk1_pts_league",
  ];

  const rows: string[] = [header.join(",")];
  let boardMatches = 0;

  const eligible: SleeperPlayer[] = Object.values(players).filter(
    (p) =>
      ["QB", "RB", "WR", "TE", "K", "DEF"].includes(p.position) && p.active !== false,
  );

  for (const player of eligible) {
    const proj = projections[player.player_id];
    const boardEntry = board.get(player.player_id);
    if (boardEntry) boardMatches++;

    const pts = boardEntry?.pts !== undefined ? boardEntry.pts : proj?.pts_half_ppr;
    const ptsSource = boardEntry?.pts !== undefined ? "board" : proj?.pts_half_ppr !== undefined ? "api" : "";

    const row = [
      player.player_id,
      sleeperPlayerFullName(player),
      player.position,
      player.team ?? "",
      boardEntry ? String(boardEntry.rank) : "",
      boardEntry?.bye ?? "",
      boardEntry?.dollar ?? "",
      round(pts),
      ptsSource,
      round(earlyWeeksPts.get(player.player_id)),
      round(week1Pts.get(player.player_id)),
    ];
    rows.push(row.map(csvCell).join(","));
  }

  mkdirSync("data", { recursive: true });
  const outPath = path.join("data", `projections-${season}.csv`);
  writeFileSync(outPath, rows.join("\n") + "\n");

  console.log(`Wrote ${eligible.length} rows to ${outPath} (${boardMatches} matched board data).`);
  console.log(
    `Weekly columns scored as "${league.name}" ` +
      `(${scoring.pass_td} pt pass TD, ${scoring.rec} PPR).`,
  );
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
