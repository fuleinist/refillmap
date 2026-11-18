# refillmap — SPEC

## Problem

A heatwave makes the walk to water dangerous. A person needs three answers fast:

1. Where is the nearest drinking fountain?
2. Where is a seat in shade?
3. Which route stays in shade?

Most map apps answer none of these. They route by the shortest path and ignore the sun.

## Users

- A walker or runner who needs water on a hot day.
- A parent with a pram who needs a shaded bench and a fountain.
- An older resident who plans a short walk between cool places.

## MVP scope

One page. Pick an area, or share a location. The page returns a plan for one hour:

- Nearest drinking fountain, with the shaded walking route.
- Nearest shaded seat, with the shaded walking route.
- Nearest cool public space. A park with canopy, or a library.
- Shade share of each route, in percent.
- A 24-hour comfort strip for the day. Apparent temperature and UV index.

## Acceptance criteria

- AC1 — The app loads an area without a network call. Bundled OpenStreetMap snapshots cover two areas.
- AC2 — A live Overpass fetch fills an unknown area. The result is cached in SQLite for 7 days.
- AC3 — Sun elevation and azimuth come from the NOAA solar position equations. A test matches the known noon elevation for Sydney to 1.5 degrees.
- AC4 — The shade mask uses building heights and tree crowns. A 10 m building at 30 degree sun elevation casts a shadow of 17.3 m in the anti-solar direction. Tolerance is 1 m.
- AC5 — The router prefers shade. At equal length, a shaded cell costs less than an open cell. A test proves this on a small grid.
- AC6 — Each target returns a route, a length in metres, a walking time and a shade share.
- AC7 — Weather comes from Open-Meteo. If the call fails, the plan still works and states that weather is unavailable.
- AC8 — The API returns HTTP 400 for a bad time value and HTTP 404 for an unknown area.
- AC9 — All tests pass with `python -m pytest`.
- AC10 — The UI is one HTML page. It draws the map on a canvas from the API payload. It uses no map tiles and no CDN.

## Non-goals

- No turn-by-turn navigation.
- No medical advice.
- No private land. The router stays on mapped paths and parks.
- No account, no tracking.

## Data

- OpenStreetMap via Overpass API. ODbL licence. Objects: fountains, benches, parks, gardens, trees, tree rows, buildings, paths, libraries, shelters.
- Open-Meteo forecast API. Free, no key. Hourly temperature, apparent temperature, UV index, humidity.
- Sun position: NOAA solar equations. Local computation.

## Model limits

- Shade is an estimate. It uses mapped trees and building footprints only.
- A tree without a crown width gets a 3.5 m radius.
- A building without a height gets 6 m. With levels, each level is 3.2 m.
- The walk grid is 7 m. The shade grid is 3 m.
- Mapped data is incomplete. A blank area is unobserved, not safe.

## Stack

Python 3.11, FastAPI, SQLite cache, vanilla JS canvas. No runtime dependencies beyond FastAPI and uvicorn.

## Layout

```
refillmap/      Python package
web/            single-page UI
data/           bundled OSM snapshots and the area list
scripts/        snapshot fetch tool
tests/          pytest suite
```