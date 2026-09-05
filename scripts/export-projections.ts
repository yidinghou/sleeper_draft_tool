import { mkdirSync, existsSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import {
  fetchPlayers,
  fetchSeasonProjections,
  fetchWeeklyProjections,
  sleeperPlayerFullName,
  type SleeperPlayer,
} from "../src/sleeper.ts";

/** Weeks summed into the early-season points column. */
const EARLY_WEEKS = [1, 2, 3];

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

  const [players, projections, weeklyProjections] = await Promise.all([
    fetchPlayers(),
    fetchSeasonProjections(season),
    Promise.all(EARLY_WEEKS.map((week) => fetchWeeklyProjections(season, week))),
  ]);
  const board = loadBoard(season);

  const earlyWeeksPts = new Map<string, number>();
  for (const weekProjections of weeklyProjections) {
    for (const [playerId, proj] of Object.entries(weekProjections)) {
      if (proj.pts_half_ppr === undefined) continue;
      earlyWeeksPts.set(playerId, (earlyWeeksPts.get(playerId) ?? 0) + proj.pts_half_ppr);
    }
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
    "wk1_3_pts_half_ppr",
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
    ];
    rows.push(row.map(csvCell).join(","));
  }

  mkdirSync("data", { recursive: true });
  const outPath = path.join("data", `projections-${season}.csv`);
  writeFileSync(outPath, rows.join("\n") + "\n");

  console.log(`Wrote ${eligible.length} rows to ${outPath} (${boardMatches} matched board data).`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
