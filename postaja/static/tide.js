// Graf gladine morja (SVG, brez knjižnic) za 10 dni:
// napovedana gladina, astronomsko plimovanje, obarvana razlika med njima (vpliv vremena),
// lunine mene in – za Tržaški zaliv – pas juga in burje. Podatki so v #tide-data.
(function () {
  const host = document.getElementById("tide");
  const src = document.getElementById("tide-data");
  if (!host || !src) return;
  const { level, astro, start_ts, moons, wind, days, t } = JSON.parse(src.textContent);
  const n = level.length;
  if (n < 2) return;

  const HOURS = days.length * 24;
  const W = 1200, M = { top: 46, right: 46, left: 40 }, PLOT = 200, STRIP = 84, GAP = 30;
  const MOONS = ["🌑", "🌓", "🌕", "🌗"];
  const bottom = M.top + PLOT;
  const stripTop = bottom + GAP, stripMid = stripTop + STRIP / 2;
  const H = (wind ? stripTop + STRIP : bottom) + 22;
  const iw = W - M.left - M.right;
  const r = (v) => Math.round(v * 10) / 10;
  const x = (h) => r(M.left + iw * h / HOURS);
  const signed = (v) => (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v);

  // Navpična os v cm; korak mreže se prilagodi razponu (Jadran nekaj dm, Severno morje nekaj m).
  const lo = Math.min(...level, ...astro), hi = Math.max(...level, ...astro);
  const step = hi - lo <= 140 ? 20 : hi - lo <= 350 ? 50 : 100;
  const yMin = Math.floor(lo / step) * step, yMax = Math.ceil(hi / step) * step;
  const y = (v) => r(M.top + PLOT * (1 - (v - yMin) / (yMax - yMin)));

  let s = "";

  // Dnevi: izmenični pasovi, ločnice in oznake
  days.forEach((day, j) => {
    const x0 = x(j * 24), x1 = x(j * 24 + 24);
    if (j % 2) s += `<rect class="c-band" x="${x0}" y="${M.top}" width="${r(x1 - x0)}" height="${H - M.top - 22}"/>`;
    if (j) s += `<line class="c-grid" x1="${x0}" x2="${x0}" y1="${M.top - 40}" y2="${H - 22}"/>`;
    s += `<text class="c-day" x="${r((x0 + x1) / 2)}" y="16">${day.name} <tspan class="c-date">${day.date}</tspan></text>`;
  });
  moons.forEach((m) => {
    s += `<text class="c-moon" x="${x(m.h)}" y="${M.top - 8}"><title>${t.moons[m.p]}</title>${MOONS[m.p]}</text>`;
  });

  // Vodoravna mreža; ničla je povprečna gladina
  for (let v = yMin; v <= yMax; v += step) {
    s += `<line class="${v === 0 ? "c-zero" : "c-grid c-dash"}" x1="${M.left}" x2="${W - M.right}" y1="${y(v)}" y2="${y(v)}"/>`;
    s += `<text class="c-axis" x="${M.left - 6}" y="${y(v) + 4}" text-anchor="end">${signed(v)}</text>`;
  }
  s += `<text class="c-axis" x="${W - M.right + 6}" y="${M.top + 4}">cm</text>`;

  // Razlika med napovedano gladino in plimovanjem, obarvana po predznaku
  let up = "", down = "";
  for (let i = 0; i < n - 1; i++) {
    const quad = `M${x(i)},${y(level[i])}L${x(i + 1)},${y(level[i + 1])}L${x(i + 1)},${y(astro[i + 1])}L${x(i)},${y(astro[i])}Z`;
    if (level[i] + level[i + 1] >= astro[i] + astro[i + 1]) up += quad; else down += quad;
  }
  s += `<path class="c-up" d="${up}"/><path class="c-down" d="${down}"/>`;

  const line = (values) => values.map((v, i) => `${i ? "L" : "M"}${x(i)},${y(v)}`).join("");
  s += `<path class="c-astro" d="${line(astro)}"/><path class="c-level" d="${line(level)}"/>`;

  // Pas vetra: jugo navzgor, burja navzdol, višina po hitrosti v vozlih
  let ktMax = 0;
  if (wind) {
    ktMax = Math.max(20, Math.ceil(Math.max(...wind.jugo, ...wind.burja) / 10) * 10);
    const area = (values, dir) =>
      `M${x(0)},${stripMid}` + values.map((v, i) => `L${x(i)},${r(stripMid - dir * v / ktMax * STRIP / 2)}`).join("") + `L${x(n - 1)},${stripMid}Z`;
    s += `<path class="c-jugo" d="${area(wind.jugo, 1)}"/><path class="c-burja" d="${area(wind.burja, -1)}"/>`;
    s += `<line class="c-zero" x1="${M.left}" x2="${W - M.right}" y1="${stripMid}" y2="${stripMid}"/>`;
    s += `<text class="c-strip" x="${M.left + 6}" y="${stripTop + 12}">${t.jugo} ↑</text>`;
    s += `<text class="c-strip" x="${M.left + 6}" y="${stripTop + STRIP - 3}">${t.burja} ↓</text>`;
    s += `<text class="c-axis" x="${W - M.right + 6}" y="${stripTop + 8}">${ktMax} kt</text>`;
    s += `<text class="c-axis" x="${W - M.right + 6}" y="${stripTop + STRIP}">${ktMax} kt</text>`;
  }

  // Oznaka "zdaj": navpičnica, pika na krivulji in trenutna gladina (med urnima vrednostma interpolirana)
  const now = (Date.now() / 1000 - start_ts) / 3600;
  if (now >= 0 && now <= n - 1) {
    const i = Math.min(Math.floor(now), n - 2);
    const value = level[i] + (level[i + 1] - level[i]) * (now - i);
    const nx = x(now), toLeft = nx > W - 160;
    s += `<line class="c-now" x1="${nx}" x2="${nx}" y1="${M.top - 14}" y2="${H - 22}"/>`;
    s += `<circle class="c-now-dot" cx="${nx}" cy="${y(value)}" r="5"/>`;
    s += `<text class="c-now-label" x="${nx + (toLeft ? -7 : 7)}" y="${M.top - 6}" style="text-anchor:${toLeft ? "end" : "start"}">`
      + `${t.now[0].toUpperCase() + t.now.slice(1)} ${signed(Math.round(value))} cm</text>`;
  }
  s += `<line class="c-guide" y1="${M.top}" y2="${H - 22}" style="display:none"/>`;
  host.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img">${s}</svg><div class="chart-tip" hidden></div>`;

  // Oblaček s podatki ob premiku miške ali dotiku
  const svg = host.firstElementChild, tip = host.lastElementChild, guide = svg.querySelector(".c-guide");
  function show(e) {
    const box = svg.getBoundingClientRect();
    const sx = (e.clientX - box.left) * W / box.width;
    const i = Math.max(0, Math.min(n - 1, Math.round((sx - M.left) / iw * HOURS)));
    const day = days[Math.floor(i / 24)];
    guide.setAttribute("x1", x(i));
    guide.setAttribute("x2", x(i));
    guide.style.display = "";
    let html = `<b>${day.name} ${day.date} ${i % 24}:00</b><br>${t.level}: ${signed(level[i])} cm`
      + `<br>${t.astro}: ${signed(astro[i])} cm<br>${t.dev}: ${signed(level[i] - astro[i])} cm`;
    if (wind && wind.jugo[i]) html += `<br>${t.jugo}: ${wind.jugo[i]} kt`;
    if (wind && wind.burja[i]) html += `<br>${t.burja}: ${wind.burja[i]} kt`;
    tip.innerHTML = html;
    tip.hidden = false;
    const px = x(i) * box.width / W;
    tip.style.left = (px > box.width / 2 ? px - tip.offsetWidth - 12 : px + 12) + "px";
  }
  function hide() {
    tip.hidden = true;
    guide.style.display = "none";
  }
  svg.addEventListener("pointermove", show);
  svg.addEventListener("pointerdown", show);
  svg.addEventListener("pointerleave", (e) => { if (e.pointerType === "mouse") hide(); });
})();
