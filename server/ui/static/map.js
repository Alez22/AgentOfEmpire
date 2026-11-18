/**
 * @file The realm's map page (docs/DESIGN.md, "The map as the realm's first
 * page", G): pan, pinch, wheel and double tap on the board; building cards
 * and the month's marks without a reload (the square's card carries the Voice).
 *
 * The page works without this script: every tap is a plain link. Here the
 * view is the SVG viewBox, kept at the screen's aspect, so one scale (screen
 * pixels per board unit) converts every gesture. No library, no timers but
 * one animation frame loop while flying to a mark.
 */
(function () {
  "use strict";

  const svg = document.querySelector(".realm-board");
  if (!svg) return;
  const hud = document.querySelector(".hud");
  const sheet = document.querySelector(".sheet");
  const more = document.querySelector(".sheet-more");
  const slot = document.getElementById("card-slot");
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const board = svg.viewBox.baseVal;
  const BOARD_W = board.width, BOARD_H = board.height;
  const realm = svg.dataset.realm.split(" ").map(Number);  // x1 y1 x2 y2 in board units
  const NEAR_SCALE = 1.3;  // from here on the zone names are readable
  const TAP_SLOP = 8;      // pixels a finger may move and still tap

  document.body.classList.add("js-map");
  svg.setAttribute("preserveAspectRatio", "xMinYMin meet");
  const view = { x: 0, y: 0, s: 1 };  // top-left corner in board units, pixels per unit

  /** @brief The screen band left free between the HUD and the sheet. */
  function freeBand() {
    const top = hud.getBoundingClientRect().bottom - 20;
    const bottom = sheet.getBoundingClientRect().top;
    return { top: top, height: Math.max(120, bottom - top) };
  }

  function limits() {
    const fitWhole = Math.min(svg.clientWidth / BOARD_W, svg.clientHeight / BOARD_H);
    return { min: fitWhole * 0.9, max: Math.max(3.2, fitWhole * 6) };
  }

  /** @brief Write the view into the viewBox. */
  function apply() {
    const width = svg.clientWidth / view.s, height = svg.clientHeight / view.s;
    svg.setAttribute("viewBox", `${view.x.toFixed(1)} ${view.y.toFixed(1)} ${width.toFixed(1)} ${height.toFixed(1)}`);
    svg.classList.toggle("near", view.s >= NEAR_SCALE);
  }

  /** @brief Frame the realm in the free band: the first thing the player sees. */
  function frameRealm() {
    const band = freeBand();
    const width = realm[2] - realm[0], height = realm[3] - realm[1];
    const { min, max } = limits();
    view.s = Math.min(max, Math.max(min, Math.min(svg.clientWidth / width, band.height / height) * 0.96));
    view.x = (realm[0] + realm[2]) / 2 - svg.clientWidth / 2 / view.s;
    view.y = (realm[1] + realm[3]) / 2 - (band.top + band.height / 2) / view.s;
    apply();
  }

  /** @brief Zoom by factor around a screen point (pixels from the svg's corner). */
  function zoomAt(px, py, factor) {
    const { min, max } = limits();
    const s = Math.min(max, Math.max(min, view.s * factor));
    view.x += px / view.s - px / s;
    view.y += py / view.s - py / s;
    view.s = s;
    apply();
  }

  /** @brief Bring a board point to the middle of the free band, smoothly unless motion is reduced. */
  function flyTo(bx, by) {
    const band = freeBand();
    const s = Math.max(view.s, NEAR_SCALE);
    const target = { x: bx - svg.clientWidth / 2 / s, y: by - (band.top + band.height / 2) / s, s: s };
    if (reducedMotion) { Object.assign(view, target); apply(); return; }
    const start = { ...view }, began = performance.now(), length = 450;
    function step(now) {
      const t = Math.min(1, (now - began) / length), ease = 1 - Math.pow(1 - t, 3);
      view.x = start.x + (target.x - start.x) * ease;
      view.y = start.y + (target.y - start.y) * ease;
      view.s = start.s + (target.s - start.s) * ease;
      apply();
      if (t < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }

  /* ---------- Gestures: one finger pans, two pinch; the wheel zooms ---------- */
  const pointers = new Map();
  let dragged = 0, lastTap = 0;

  function local(event) {
    const rect = svg.getBoundingClientRect();
    return [event.clientX - rect.left, event.clientY - rect.top];
  }

  svg.addEventListener("pointerdown", (event) => {
    pointers.set(event.pointerId, local(event));
    if (pointers.size === 1) dragged = 0;
  });
  window.addEventListener("pointermove", (event) => {
    if (!pointers.has(event.pointerId)) return;
    const before = [...pointers.values()];
    pointers.set(event.pointerId, local(event));
    const after = [...pointers.values()];
    if (after.length === 1) {
      const dx = after[0][0] - before[0][0], dy = after[0][1] - before[0][1];
      dragged += Math.abs(dx) + Math.abs(dy);
      view.x -= dx / view.s;
      view.y -= dy / view.s;
      apply();
    } else if (after.length === 2) {
      dragged += TAP_SLOP;  // a pinch is never a tap
      const span = (p) => Math.hypot(p[0][0] - p[1][0], p[0][1] - p[1][1]);
      const mid = [(after[0][0] + after[1][0]) / 2, (after[0][1] + after[1][1]) / 2];
      const midBefore = [(before[0][0] + before[1][0]) / 2, (before[0][1] + before[1][1]) / 2];
      view.x -= (mid[0] - midBefore[0]) / view.s;
      view.y -= (mid[1] - midBefore[1]) / view.s;
      if (span(before) > 0) zoomAt(mid[0], mid[1], span(after) / span(before));
      else apply();
    }
  });
  function release(event) {
    if (!pointers.has(event.pointerId)) return;
    pointers.delete(event.pointerId);
  }
  window.addEventListener("pointerup", release);
  window.addEventListener("pointercancel", release);

  svg.addEventListener("wheel", (event) => {
    event.preventDefault();
    const [px, py] = local(event);
    zoomAt(px, py, Math.exp(-event.deltaY * 0.0015));
  }, { passive: false });

  /* ---------- Taps: buildings, marks, empty land ---------- */
  svg.addEventListener("click", (event) => {
    if (dragged > TAP_SLOP) { event.preventDefault(); return; }  // the end of a pan, not a tap
    const now = Date.now();
    if (now - lastTap < 300) {  // double tap: zoom in where the finger is
      event.preventDefault();
      const [px, py] = local(event);
      zoomAt(px, py, 1.7);
      lastTap = 0;
      return;
    }
    lastTap = now;
    const building = event.target.closest("[data-b]");
    const pin = event.target.closest(".pin");
    if (building) { event.preventDefault(); showCard(building); return; }
    if (pin) { event.preventDefault(); lightMark(pin.id.replace("mark-", ""), true); return; }
    clearChoice();
    if (more) more.open = false;
  });

  function clearChoice() {
    slot.replaceChildren();
    document.querySelectorAll(".sheet > .sheet-card").forEach((card) => card.remove());  // the server's card, if any
    svg.querySelectorAll(".map-building.chosen-js").forEach((link) => link.classList.remove("chosen-js"));
    svg.querySelectorAll(".chosen").forEach((line) => line.remove());
    svg.querySelectorAll(".pin.lit").forEach((pin) => pin.classList.remove("lit"));
    document.querySelectorAll(".month-lines a.lit").forEach((line) => line.classList.remove("lit"));
  }

  /** @brief The building's card on top of the sheet, from its <template>. */
  function showCard(link) {
    const template = document.getElementById(`card-${link.dataset.b}`);
    if (!template) { window.location = link.getAttribute("href"); return; }
    clearChoice();
    slot.replaceChildren(template.content.cloneNode(true));
    link.classList.add("chosen-js");
    if (more) more.open = false;
  }

  /** @brief Light a month's mark and its line in the sheet. */
  function lightMark(id, openSheet) {
    const pin = document.getElementById(`mark-${id}`);
    if (!pin) return;
    clearChoice();
    pin.classList.add("lit");
    const line = document.querySelector(`.month-lines a[href="?m=${id}"]`);
    if (line) line.classList.add("lit");
    if (openSheet && more) {
      more.open = true;
      if (line) line.scrollIntoView({ block: "nearest" });
    }
  }

  /* A line of the month past flies the map to its mark. */
  document.querySelectorAll(".month-lines a[href^='?m=']").forEach((line) => {
    line.addEventListener("click", (event) => {
      const id = line.getAttribute("href").slice(3);
      const disc = document.querySelector(`#mark-${id} .pin-disc`);
      if (!disc) return;
      event.preventDefault();
      if (more) more.open = false;
      lightMark(id, false);
      flyTo(Number(disc.getAttribute("cx")), Number(disc.getAttribute("cy")));
    });
  });

  window.addEventListener("resize", frameRealm);
  frameRealm();
  const lit = new URLSearchParams(window.location.search).get("m");
  if (lit) lightMark(lit, false);
})();
