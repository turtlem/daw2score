// Convert a Guitar Pro 5 file to Guitar Pro 7/8 (.gp) with alphaTab's GP7 exporter.
// usage: node gp5togp.mjs <in.gp5> <out.gp>
import * as alphaTab from "@coderline/alphatab";
import fs from "node:fs";

const [src, dst] = process.argv.slice(2);
if (!src || !dst) {
  console.error("usage: node gp5togp.mjs <in.gp5> <out.gp>");
  process.exit(2);
}
const score = alphaTab.importer.ScoreLoader.loadScoreFromBytes(new Uint8Array(fs.readFileSync(src)));
fs.writeFileSync(dst, new alphaTab.exporter.Gp7Exporter().export(score));
console.log(`converted to ${dst}: ${score.tracks.length} tracks, ${score.masterBars.length} bars`);
