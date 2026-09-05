import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fetchPlayers, sleeperPlayerFullName, type SleeperPlayer } from "../src/sleeper.ts";
import {
  buildPlayerIndex,
  fetchBobertoAav,
  fetchBobertoProjections,
  matchSleeperPlayer,
  normalizeTeam,
  type BobertoStats,
} from "../src/boberto.ts";

/** Raw stat columns, in emit order — the union of every position's stat keys. */
const STAT_COLUMNS = [
  "pass_yds",
  "pass_tds",
  "pass_ints",
  "rush_yds",
  "rush_tds",
  "rec_yds",
  "rec_tds",
  "receptions",
  "fumbles_lost",
  "fg_0_39",
  "pat_made",
  "def_sacks",
  "def_ints",
  "def_fumble_recoveries",
  "def_tds",
  "def_safeties",
];

const AAV_SOURCES = ["espn", "nffc", "yahoo"];

/**
 * Half-PPR points from a projected stat line.
 *
 * ponytail: K and DEF are approximate — the feed carries no field-goal distance
 * buckets and no points-allowed, so those two positions are rough. Upgrade only
 * if K/DEF pricing ever matters.
 */
function halfPprPoints(stats: BobertoStats): number {
  const s = (key: string) => stats[key] ?? 0;
  return (
    s("pass_yds") / 25 +
    s("pass_tds") * 4 -
    s("pass_ints") * 2 +
    s("rush_yds") / 10 +
    s("rush_tds") * 6 +
    s("rec_yds") / 10 +
    s("rec_tds") * 6 +
    s("receptions") * 0.5 -
    s("fumbles_lost") * 2 +
    s("fg_0_39") * 3 +
    s("pat_made") +
    s("def_sacks") +
    s("def_ints") * 2 +
    s("def_fumble_recoveries") * 2 +
    s("def_tds") * 6 +
    s("def_safeties") * 2
  );
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

async function main() {
  const season = Number(process.argv[2] ?? 2026);

  const [players, projections, aav] = await Promise.all([
    fetchPlayers(),
    fetchBobertoProjections(season),
    fetchBobertoAav(season),
  ]);
  const index = buildPlayerIndex(players);

  // player_id -> aav, per source. Unmatched AAV rows are dropped.
  const aavById = new Map<string, Map<string, number>>();
  let unmatchedAav = 0;
  for (const source of AAV_SOURCES) {
    for (const entry of aav.sources[source] ?? []) {
      const player = matchSleeperPlayer(index, entry);
      if (!player) {
        unmatchedAav++;
        continue;
      }
      const bySource = aavById.get(player.player_id) ?? new Map<string, number>();
      bySource.set(source, entry.aav);
      aavById.set(player.player_id, bySource);
    }
  }

  const header = [
    "player_id",
    "player",
    "position",
    "team",
    "bye_week",
    "season_pts_half_ppr",
    ...AAV_SOURCES.map((s) => `aav_${s}`),
    ...STAT_COLUMNS,
  ];

  const rows: string[] = [header.join(",")];
  const unmatched: string[] = [];

  for (const proj of projections) {
    const player: SleeperPlayer | null = matchSleeperPlayer(index, {
      name: proj.playerName,
      position: proj.position,
      team: proj.team,
    });
    if (!player) unmatched.push(`${proj.playerName} (${proj.position}, ${proj.team ?? "FA"})`);

    const bySource = player ? aavById.get(player.player_id) : undefined;

    rows.push(
      [
        player?.player_id ?? "",
        player ? sleeperPlayerFullName(player) : proj.playerName,
        player?.position ?? proj.position,
        (player ? player.team : normalizeTeam(proj.team)) ?? "",
        proj.bye === undefined ? "" : String(proj.bye),
        round(halfPprPoints(proj.stats)),
        ...AAV_SOURCES.map((s) => round(bySource?.get(s))),
        ...STAT_COLUMNS.map((key) => round(proj.stats[key])),
      ]
        .map(csvCell)
        .join(","),
    );
  }

  mkdirSync("data", { recursive: true });
  const outPath = path.join("data", `boberto-${season}.csv`);
  writeFileSync(outPath, rows.join("\n") + "\n");

  console.log(
    `Wrote ${projections.length} rows to ${outPath} ` +
      `(${projections.length - unmatched.length} matched a Sleeper id, ${unmatched.length} unmatched; ` +
      `${unmatchedAav} AAV rows dropped).`,
  );
  if (unmatched.length) {
    console.log("Unmatched — add a NAME_ALIASES entry in src/boberto.ts for any of these:");
    for (const name of unmatched) console.log(`  ${name}`);
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
