/* refillmap UI: canvas map, shaded routes, comfort strip. No libraries. */

const ROUTE_COLORS = { water: "#1f7ae0", seat: "#d97706", cool: "#0f766e" };
const BAND_COLORS = {
  cool: "#7fb3d5",
  mild: "#9fc98a",
  warm: "#f0c05a",
  hot: "#e8894a",
  severe: "#cc4b36",
  unknown: "#d9e2e8",
};

const state = {
  areas: [],
  plan: null,
  active: "water",
  bitmap: null,
};

const el = (id) => document.getElementById(id);
const canvas = el("map");
const ctx = canvas.getContext("2d");

function setStatus(text, isError = false) {
  const node = el("status");
  node.textContent = text;
  node.classList.toggle("error", Boolean(isError));
}

function localInputValue(date) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function decodeBits(base64, width, height) {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  const alpha = new Uint8ClampedArray(width * height);
  for (let j = 0; j < height; j += 1) {
    for (let i = 0; i < width; i += 1) {
      const index = j * width + i;
      const bit = (bytes[index >> 3] >> (7 - (index & 7))) & 1;
      alpha[index] = bit ? 150 : 0;
    }
  }
  return alpha;
}

function makeProjector(bbox, width, height, pad) {
  const midLat = (bbox.south + bbox.north) / 2;
  const mPerDegLat = 110540;
  const mPerDegLon = 111320 * Math.cos((midLat * Math.PI) / 180);
  const extentX = (bbox.east - bbox.west) * mPerDegLon;
  const extentY = (bbox.north - bbox.south) * mPerDegLat;
  const scale = Math.min((width - 2 * pad) / extentX, (height - 2 * pad) / extentY);
  const offX = (width - extentX * scale) / 2;
  const offY = (height - extentY * scale) / 2;
  return (lat, lon) => [
    offX + (lon - bbox.west) * mPerDegLon * scale,
    offY + (bbox.north - lat) * mPerDegLat * scale,
  ];
}

function polygonPath(project, ring) {
  ctx.beginPath();
  ring.forEach((point, index) => {
    const [x, y] = project(point[0], point[1]);
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.closePath();
}

function drawShadowLayer(project, bbox, plan) {
  const bitmap = plan.shade.bitmap;
  const cols = bitmap.width;
  const rows = bitmap.height;
  const alpha = decodeBits(bitmap.bits, cols, rows);

  const off = document.createElement("canvas");
  off.width = cols;
  off.height = rows;
  const offCtx = off.getContext("2d");
  const image = offCtx.createImageData(cols, rows);
  for (let i = 0; i < alpha.length; i += 1) {
    const offset = i * 4;
    image.data[offset] = 74;
    image.data[offset + 1] = 104;
    image.data[offset + 2] = 140;
    image.data[offset + 3] = alpha[i];
  }
  offCtx.putImageData(image, 0, 0);

  const [x0, y0] = project(bbox.north, bbox.west);
  const [x1, y1] = project(bbox.south, bbox.east);
  ctx.save();
  ctx.imageSmoothingEnabled = true;
  ctx.drawImage(off, x0, y0, x1 - x0, y1 - y0);
  ctx.restore();
}

function drawMap() {
  const plan = state.plan;
  if (!plan) return;

  const ratio = window.devicePixelRatio || 1;
  const cssWidth = canvas.clientWidth;
  const cssHeight = canvas.clientHeight;
  canvas.width = Math.round(cssWidth * ratio);
  canvas.height = Math.round(cssHeight * ratio);
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);

  const bbox = plan.area.bbox;
  const project = makeProjector(bbox, cssWidth, cssHeight, 18);

  ctx.fillStyle = "#f7ecd2";
  ctx.fillRect(0, 0, cssWidth, cssHeight);

  const map = plan.map;

  for (const park of map.parks) {
    polygonPath(project, park.ring);
    ctx.fillStyle = park.kind === "garden" ? "#c9dfba" : "#c2dcb0";
    ctx.fill();
  }

  ctx.strokeStyle = "rgba(255,255,255,0.75)";
  ctx.lineWidth = 1.4;
  ctx.lineCap = "round";
  for (const way of map.paths) {
    ctx.beginPath();
    way.forEach((point, index) => {
      const [x, y] = project(point[0], point[1]);
      if (index === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
  }

  for (const ring of map.buildings) {
    polygonPath(project, ring);
    ctx.fillStyle = "#ded2bd";
    ctx.fill();
    ctx.strokeStyle = "rgba(146,132,108,0.55)";
    ctx.lineWidth = 0.7;
    ctx.stroke();
  }

  for (const tree of map.trees) {
    const [x, y] = project(tree[0], tree[1]);
    const radius = Math.max(1.4, tree[2] * (cssWidth / (bbox.east - bbox.west) / 111320 / Math.cos((bbox.south * Math.PI) / 180)));
    ctx.beginPath();
    ctx.arc(x, y, radius, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(94,140,74,0.42)";
    ctx.fill();
  }

  drawShadowLayer(project, bbox, plan);

  const target = plan.targets[state.active];
  for (const key of ["water", "seat", "cool"]) {
    const item = plan.targets[key];
    if (!item || key !== state.active) continue;
    const points = item.route.points;
    ctx.beginPath();
    points.forEach((point, index) => {
      const [x, y] = project(point[0], point[1]);
      if (index === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.strokeStyle = "rgba(255,255,255,0.9)";
    ctx.lineWidth = 7.5;
    ctx.stroke();
    ctx.strokeStyle = ROUTE_COLORS[key];
    ctx.lineWidth = 4.2;
    ctx.stroke();
  }

  const [ox, oy] = project(plan.origin.lat, plan.origin.lon);
  ctx.beginPath();
  ctx.arc(ox, oy, 7, 0, Math.PI * 2);
  ctx.fillStyle = "#1b1f24";
  ctx.fill();
  ctx.strokeStyle = "#fff";
  ctx.lineWidth = 2.4;
  ctx.stroke();

  if (target) {
    const [tx, ty] = project(target.spot.lat, target.spot.lon);
    const color = ROUTE_COLORS[state.active];
    ctx.beginPath();
    ctx.arc(tx, ty, 9, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.fill();
    ctx.strokeStyle = "#fff";
    ctx.lineWidth = 2.8;
    ctx.stroke();

    ctx.font = "600 12px 'Segoe UI', Arial, sans-serif";
    const label = target.spot.name;
    const width = ctx.measureText(label).width + 12;
    let lx = tx + 14;
    if (lx + width > cssWidth - 6) lx = tx - 14 - width;
    const ly = Math.max(14, ty - 10);
    ctx.fillStyle = "rgba(255,255,255,0.94)";
    ctx.strokeStyle = "rgba(27,31,36,0.16)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.roundRect(lx, ly - 13, width, 22, 7);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = "#1b1f24";
    ctx.fillText(label, lx + 6, ly + 2);
  }
}

function weatherLine(plan) {
  const weather = plan.weather;
  if (!weather || !weather.available) {
    return "Weather is unavailable. The plan still uses the sun position and mapped shade.";
  }
  const now = weather.now;
  if (now.apparentC === null || now.apparentC === undefined) {
    return "Weather is loaded, but the current hour has no value.";
  }
  const parts = [
    `Feels like ${Math.round(now.apparentC)} °C`,
    now.tempC !== null ? `air ${Math.round(now.tempC)} °C` : null,
    now.uvIndex !== null && now.uvIndex !== undefined ? `UV ${now.uvIndex.toFixed(1)}` : null,
    now.humidity !== null && now.humidity !== undefined ? `humidity ${Math.round(now.humidity)}%` : null,
  ].filter(Boolean);
  return parts.join(" · ");
}

function routeWhy(item, label) {
  if (!item) return `No ${label} found near this point.`;
  const route = item.route;
  const bits = [];
  bits.push(`${Math.round(route.lengthM)} m walk, ${route.minutes} min`);
  bits.push(`${route.shadePct}% of the walk in shade`);
  if (item.spot.indoor) bits.push("indoor refuge");
  if (item.spot.note) bits.push(item.spot.note);
  return bits.join(" · ");
}

function renderPanel(plan) {
  const water = plan.targets.water;
  const seat = plan.targets.seat;
  const cool = plan.targets.cool;

  el("waterName").textContent = water ? water.spot.name : "No mapped fountain";
  el("waterMeta").innerHTML = water
    ? `<strong>${Math.round(water.route.lengthM)} m</strong> · ${water.route.minutes} min · ${water.route.shadePct}% shade`
    : "Try another area or start point.";
  el("waterWhy").textContent = water
    ? routeWhy(water, "fountain")
    : "No drinking water is mapped near this start point.";

  el("seatName").textContent = seat ? seat.spot.name : "No mapped bench";
  el("seatMeta").innerHTML = seat
    ? `<strong>${Math.round(seat.route.lengthM)} m</strong> · ${seat.route.minutes} min · seat ${
        seat.spot.shaded ? "in shade now" : "in sun now"
      }`
    : "Try another area or start point.";
  el("seatWhy").textContent = seat
    ? `${seat.route.shadePct}% of the walk in shade${seat.spot.note ? " · " + seat.spot.note : ""}`
    : "No public bench is mapped near this start point.";

  el("coolName").textContent = cool ? cool.spot.name : "No mapped cool space";
  el("coolMeta").innerHTML = cool
    ? `<strong>${Math.round(cool.route.lengthM)} m</strong> · ${cool.route.minutes} min · ${
        cool.spot.indoor ? "indoor" : `${cool.spot.shadePct}% canopy shade`
      }`
    : "Try another area or start point.";
  el("coolWhy").textContent = cool
    ? routeWhy(cool, "cool space")
    : "No park, garden or library is mapped near this start point.";

  for (const card of document.querySelectorAll(".card")) {
    card.classList.toggle("active", card.dataset.kind === state.active);
  }
}

function renderComfort(plan) {
  const strip = el("comfortStrip");
  strip.innerHTML = "";
  const weather = plan.weather;
  if (!weather || !weather.available || !weather.hours.length) {
    el("comfortSource").textContent = "No weather data for this hour.";
    el("bestWindows").textContent = "";
    return;
  }
  el("comfortSource").textContent = `${weather.source} · ${weather.now.time || ""}`;

  const temps = weather.hours.map((hour) => hour.apparentC).filter((v) => v !== null);
  const min = Math.min(...temps, 12);
  const max = Math.max(...temps, min + 6);

  for (const hour of weather.hours) {
    const bar = document.createElement("div");
    bar.className = `bar band-${hour.band}`;
    const value = hour.apparentC === null ? min : hour.apparentC;
    const height = 10 + (88 * (value - min)) / Math.max(1, max - min);
    bar.style.height = `${Math.max(8, Math.min(96, height))}%`;
    bar.dataset.tip = `${hour.time.slice(11, 16)} · feels ${hour.apparentC === null ? "–" : Math.round(hour.apparentC)} °C · UV ${
      hour.uvIndex === null ? "–" : hour.uvIndex.toFixed(1)
    }`;
    if (hour.time.endsWith(":00")) {
      const label = document.createElement("span");
      label.textContent = hour.time.slice(11, 13);
      bar.appendChild(label);
    }
    strip.appendChild(bar);
  }

  const windows = weather.bestWindows || [];
  if (windows.length) {
    const text = windows
      .map((window) => `${window.time.slice(11, 16)} (feels ${Math.round(window.apparentC)} °C)`)
      .join(", ");
    el("bestWindows").textContent = `Coolest hours today: ${text}.`;
  } else {
    el("bestWindows").textContent = "";
  }
}

function renderSun(plan) {
  const badge = el("sunBadge");
  badge.hidden = false;
  const sun = plan.sun;
  el("sunText").textContent = sun.isDay
    ? `Sun ${sun.elevation.toFixed(0)}° high, bearing ${sun.azimuth.toFixed(0)}°`
    : "Sun is below the horizon";
  el("mapNote").textContent = sun.isDay
    ? `Shadow cast toward ${((sun.azimuth + 180) % 360).toFixed(0)}°.`
    : "Night: shade does not matter now.";
}

function renderNotes(plan) {
  const list = el("notesList");
  list.innerHTML = "";
  for (const note of plan.notes || []) {
    const item = document.createElement("li");
    item.textContent = note;
    list.appendChild(item);
  }
}

function renderAll() {
  if (!state.plan) return;
  drawMap();
  renderPanel(state.plan);
  renderComfort(state.plan);
  renderSun(state.plan);
  renderNotes(state.plan);
}

function planUrl() {
  const params = new URLSearchParams();
  const areaId = el("areaSelect").value;
  params.set("area", areaId);
  const timeValue = el("timeInput").value;
  if (timeValue) {
    const local = new Date(timeValue);
    params.set("at", local.toISOString());
  }
  params.set("shade", el("shadeInput").value);
  params.set("weather", "1");
  if (state.custom && areaId === "__here__") {
    params.set("area", "here");
    params.set("lat", state.custom.lat.toFixed(5));
    params.set("lon", state.custom.lon.toFixed(5));
  }
  return `/api/plan?${params.toString()}`;
}

async function loadPlan() {
  if (state.loading) return;
  state.loading = true;
  const areaId = el("areaSelect").value;
  setStatus(areaId === "__here__" ? "Fetching OpenStreetMap data for your location. This can take up to a minute…" : "Building the plan…");
  const started = performance.now();
  try {
    const response = await fetch(planUrl());
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || `Request failed with ${response.status}`);
    }
    state.plan = await response.json();
    renderAll();
    syncUrl();
    setStatus(`Plan ready in ${((performance.now() - started) / 1000).toFixed(1)} s for ${state.plan.area.name}.`);
  } catch (error) {
    setStatus(`Could not build the plan: ${error.message}`, true);
  } finally {
    state.loading = false;
  }
}

async function loadAreas() {
  const response = await fetch("/api/areas");
  const payload = await response.json();
  state.areas = payload.areas;
  const select = el("areaSelect");
  select.innerHTML = "";
  for (const area of state.areas) {
    const option = document.createElement("option");
    option.value = area.id;
    option.textContent = area.name;
    if (area.note) option.title = area.note;
    select.appendChild(option);
  }
  if (!state.areas.some((area) => area.id === "newtown")) {
    select.selectedIndex = 0;
  }
}

function useMyLocation() {
  if (!navigator.geolocation) {
    setStatus("This browser has no location support.", true);
    return;
  }
  setStatus("Asking the browser for your location…");
  navigator.geolocation.getCurrentPosition(
    (position) => {
      state.custom = { lat: position.coords.latitude, lon: position.coords.longitude };
      if (!document.querySelector('option[value="__here__"]')) {
        const option = document.createElement("option");
        option.value = "__here__";
        option.textContent = "My location";
        el("areaSelect").appendChild(option);
      }
      el("areaSelect").value = "__here__";
      loadPlan();
    },
    (error) => setStatus(`Location failed: ${error.message}`, true),
    { enableHighAccuracy: false, timeout: 10000, maximumAge: 600000 },
  );
}

function bind() {
  el("planBtn").addEventListener("click", () => loadPlan());
  el("hereBtn").addEventListener("click", useMyLocation);
  el("areaSelect").addEventListener("change", () => loadPlan());
  el("timeInput").addEventListener("change", () => loadPlan());

  let shadeTimer = null;
  el("shadeInput").addEventListener("input", (event) => {
    el("shadeOut").textContent = event.target.value;
    clearTimeout(shadeTimer);
    shadeTimer = setTimeout(() => loadPlan(), 320);
  });

  for (const button of document.querySelectorAll("[data-route]")) {
    button.addEventListener("click", () => {
      state.active = button.dataset.route;
      renderPanel(state.plan);
      drawMap();
    });
  }

  for (const card of document.querySelectorAll(".card")) {
    card.addEventListener("click", (event) => {
      if (event.target.closest("[data-route]")) return;
      state.active = card.dataset.kind;
      renderPanel(state.plan);
      drawMap();
    });
  }

  window.addEventListener("resize", () => drawMap());
}

function applyUrlState() {
  const params = new URLSearchParams(window.location.search);
  const shade = params.get("shade");
  if (shade !== null && !Number.isNaN(Number(shade))) {
    el("shadeInput").value = shade;
    el("shadeOut").textContent = shade;
  }
  const at = params.get("at");
  if (at) {
    const parsed = new Date(at);
    if (!Number.isNaN(parsed.getTime())) el("timeInput").value = localInputValue(parsed);
  }
  const areaId = params.get("area");
  if (areaId && state.areas.some((area) => area.id === areaId)) {
    el("areaSelect").value = areaId;
  }
}

function syncUrl() {
  const params = new URLSearchParams();
  params.set("area", el("areaSelect").value);
  if (el("timeInput").value) params.set("at", el("timeInput").value);
  params.set("shade", el("shadeInput").value);
  history.replaceState(null, "", `${window.location.pathname}?${params.toString()}`);
}

async function boot() {
  el("timeInput").value = localInputValue(new Date());
  bind();
  try {
    await loadAreas();
  } catch (error) {
    setStatus(`Could not load the area list: ${error.message}`, true);
    return;
  }
  applyUrlState();
  await loadPlan();
  syncUrl();
}

boot();