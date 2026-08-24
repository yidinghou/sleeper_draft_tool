import { mkdirSync, existsSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import {
  fetchPlayers,
  fetchSeasonProjections,
  sleeperPlayerFullName,
  type SleeperPlayer,
} from "../src/sleeper.ts";

interface BoardEntry {
  rank: number;
  bye: string;
  dollar: string;
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
    const [playerId, rank, bye, dollar] = line.split(",");
    board.set(playerId, { rank: Number(rank), bye, dollar });
  }
  return board;
}

async function main() {
  const season = Number(process.argv[2] ?? 2026);

  const [players, projections] = await Promise.all([
    fetchPlayers(),
    fetchSeasonProjections(season),
  ]);
  const board = loadBoard(season);

  const header = [
    "player_id",
    "player",
    "position",
    "team",
    "sleeper_rank",
    "bye_week",
    "sleeper_proj_dollar",
    "season_pts_half_ppr",
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

    const row = [
      player.player_id,
      sleeperPlayerFullName(player),
      player.position,
      player.team ?? "",
      boardEntry ? String(boardEntry.rank) : "",
      boardEntry?.bye ?? "",
      boardEntry?.dollar ?? "",
      round(proj?.pts_half_ppr),
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
