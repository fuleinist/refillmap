// Standalone Overpass fetch + slim snapshot writer (build-time tool).
// Usage: node scripts/fetch_snapshot.mjs <outfile> <name> <south,west,north,east>
import { writeFileSync, mkdirSync } from "node:fs";
import { dirname } from "node:path";

const [outfile, name, bboxArg] = process.argv.slice(2);
if (!outfile || !bboxArg) {
  console.error("usage: node scripts/fetch_snapshot.mjs <outfile> <name> <s,w,n,e>");
  process.exit(2);
}
const [south, west, north, east] = bboxArg.split(",").map(Number);
const b = `${south},${west},${north},${east}`;
const q = `[out:json][timeout:90];
(
  node["amenity"="drinking_water"](${b});
  way["amenity"="drinking_water"](${b});
  node["amenity"="bench"](${b});
  way["amenity"="bench"](${b});
  way["leisure"="park"](${b});
  way["leisure"="garden"](${b});
  node["natural"="tree"](${b});
  way["natural"="tree_row"](${b});
  way["building"](${b});
  way["highway"~"^(footway|path|pedestrian|steps|residential|living_street|service|unclassified|tertiary|secondary|primary)$"](${b});
  node["amenity"="library"](${b});
  way["amenity"="library"](${b});
  node["amenity"="shelter"](${b});
);
out geom;`;

const round = (v) => Math.round(v * 1e6) / 1e6;
const KEEP = {
  building: ["building", "height", "building:levels", "name"],
  tree: ["natural", "height", "diameter_crown", "species", "genus"],
  tree_row: ["natural"],
  park: ["leisure", "name"],
  garden: ["leisure", "name"],
  fountain: ["amenity", "name", "access", "wheelchair", "drinking_water", "fee"],
  bench: ["amenity", "name", "backrest", "material", "access"],
  library: ["amenity", "name", "opening_hours", "wheelchair"],
  shelter: ["amenity", "name", "shelter_type"],
  path: ["highway", "name", "footway", "surface", "access"],
};

function kindOf(t = {}) {
  if (t.amenity === "drinking_water") return "fountain";
  if (t.amenity === "bench") return "bench";
  if (t.amenity === "library") return "library";
  if (t.amenity === "shelter") return "shelter";
  if (t.leisure === "park") return "park";
  if (t.leisure === "garden") return "garden";
  if (t.natural === "tree") return "tree";
  if (t.natural === "tree_row") return "tree_row";
  if (t.building) return "building";
  if (t.highway) return "path";
  return null;
}

const t0 = Date.now();
const res = await fetch("https://overpass-api.de/api/interpreter", {
  method: "POST",
  headers: {
    "Content-Type": "application/x-www-form-urlencoded",
    "User-Agent": "refillmap-snapshot/0.1 (github.com/fuleinist/refillmap)",
  },
  body: new URLSearchParams({ data: q }),
});
if (!res.ok) {
  console.error("FATAL: Overpass returned", res.status, await res.text().then((t) => t.slice(0, 300)));
  process.exit(1);
}
const raw = await res.json();
const features = [];
for (const el of raw.elements) {
  const t = el.tags || {};
  const kind = kindOf(t);
  if (!kind) continue;
  const keep = {};
  for (const key of KEEP[kind] || []) if (t[key] !== undefined) keep[key] = t[key];
  if (kind === "tree") {
    if (el.type !== "node" || !Number.isFinite(el.lat)) continue;
    features.push({ k: "tree", at: [round(el.lat), round(el.lon)], t: keep });
  } else if (kind === "fountain" || kind === "bench" || kind === "library" || kind === "shelter") {
    if (el.type === "node") {
      features.push({ k: kind, at: [round(el.lat), round(el.lon)], t: keep });
    } else if (el.geometry?.length) {
      const pts = el.geometry.filter((p) => p && Number.isFinite(p.lat)).map((p) => [round(p.lat), round(p.lon)]);
      if (pts.length) {
        const lat = pts.reduce((a, p) => a + p[0], 0) / pts.length;
        const lon = pts.reduce((a, p) => a + p[1], 0) / pts.length;
        features.push({ k: kind, at: [round(lat), round(lon)], t: keep });
      }
    }
  } else {
    const pts = (el.geometry || []).filter((p) => p && Number.isFinite(p.lat)).map((p) => [round(p.lat), round(p.lon)]);
    if (pts.length >= 2) features.push({ k: kind, path: pts, t: keep });
  }
}

const out = {
  v: 1,
  name: name || "area",
  bbox: { south, west, north, east },
  fetchedAt: new Date().toISOString(),
  source: "OpenStreetMap via Overpass API (ODbL)",
  features,
};
mkdirSync(dirname(outfile), { recursive: true });
const text = JSON.stringify(out);
writeFileSync(outfile, text);
console.log(
  `SAVED ${outfile} features=${features.length} bytes=${text.length} ms=${Date.now() - t0}`,
);