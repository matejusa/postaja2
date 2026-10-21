// 10-dnevni graf (SVG, brez knjižnic): temperatura z ikonami, sunki vetra,
// padavine na 4 ure in smer vetra ob 8h in 20h. Podatki so v #chart-data.
(function () {
  const host = document.getElementById("chart");
  const src = document.getElementById("chart-data");
  if (!host || !src) return;
  const { points, days } = JSON.parse(src.textContent);
  if (points.length < 2) return;

  const W = 1200, H = 440, M = { top: 52, right: 46, bottom: 72, left: 40 };
  const RAIN_MIN = 0.2; // manjše količine se ne rišejo
  const COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];
  const n = points.length;
  const iw = W - M.left - M.right, ih = H - M.top - M.bottom, bottom = M.top + ih;
  const step = iw / n;
  const r = (v) => Math.round(v * 10) / 10;
  const x = (i) => r(M.left + step * (i + 0.5));

  const temps = points.map((p) => p.temp);
  const tMin = Math.floor((Math.min(...temps) - 5) / 5) * 5;
  const tMax = Math.ceil((Math.max(...temps) + 5) / 5) * 5;
  // Desna os (kt in mm) je privzeto 0–50, ob hujših sunkih se raztegne.
  const wMax = Math.max(50, Math.ceil(Math.max(...points.map((p) => p.gust)) / 10) * 10);
  const yT = (v) => r(M.top + ih * (1 - (v - tMin) / (tMax - tMin)));
  const yW = (v) => r(M.top + ih * (1 - v / wMax));

  // Monotona kubična interpolacija (Fritsch–Carlson): gladka krivulja brez prenihajev.
  function curve(pts) {
    const k = pts.length, dx = [], m = [], t = new Array(k);
    for (let i = 0; i < k - 1; i++) {
      dx[i] = pts[i + 1][0] - pts[i][0];
      m[i] = (pts[i + 1][1] - pts[i][1]) / dx[i];
    }
    t[0] = m[0];
    t[k - 1] = m[k - 2];
    for (let i = 1; i < k - 1; i++) t[i] = m[i - 1] * m[i] <= 0 ? 0 : (m[i - 1] + m[i]) / 2;
    for (let i = 0; i < k - 1; i++) {
      if (m[i] === 0) { t[i] = t[i + 1] = 0; continue; }
      const a = t[i] / m[i], b = t[i + 1] / m[i], s = a * a + b * b;
      if (s > 9) {
        const f = 3 / Math.sqrt(s);
        t[i] = f * a * m[i];
        t[i + 1] = f * b * m[i];
      }
    }
    let d = `M${pts[0][0]},${pts[0][1]}`;
    for (let i = 0; i < k - 1; i++) {
      const h = dx[i] / 3;
      d += `C${r(pts[i][0] + h)},${r(pts[i][1] + t[i] * h)} ${r(pts[i + 1][0] - h)},${r(pts[i + 1][1] - t[i + 1] * h)} ${pts[i + 1][0]},${pts[i + 1][1]}`;
    }
    return d;
  }

  let s = `<defs>
    <linearGradient id="g-temp" x1="0" y1="0" x2="0" y2="1">
      <stop offset="5%" stop-color="#f43f5e" stop-opacity=".25"/><stop offset="95%" stop-color="#f43f5e" stop-opacity="0"/>
    </linearGradient>
    <linearGradient id="g-gust" gradientUnits="userSpaceOnUse" x1="0" y1="${M.top}" x2="0" y2="${bottom}">
      <stop offset="0" stop-color="#a855f7"/><stop offset=".6" stop-color="#eab308"/><stop offset="1" stop-color="#eab308"/>
    </linearGradient>
  </defs>`;

  // Dnevi: izmenični pasovi, ločnice in oznake nad grafom
  const starts = [];
  points.forEach((p, i) => { if (i === 0 || p.d !== points[i - 1].d) starts.push(i); });
  starts.forEach((from, j) => {
    const to = j + 1 < starts.length ? starts[j + 1] : n;
    const x0 = r(M.left + step * from), x1 = r(M.left + step * to);
    if (j % 2) s += `<rect class="c-band" x="${x0}" y="${M.top}" width="${r(x1 - x0)}" height="${ih}"/>`;
    if (j) s += `<line class="c-grid" x1="${x0}" x2="${x0}" y1="${M.top - 34}" y2="${bottom}"/>`;
    const day = days[points[from].d], mid = r((x0 + x1) / 2);
    if (to - from >= 3) {
      s += `<text class="c-day" x="${mid}" y="20">${day.name}</text><text class="c-date" x="${mid}" y="35">${day.date}</text>`;
    }
  });

  // Vodoravna mreža in osi
  for (let v = tMin; v <= tMax; v += 5) {
    s += `<line class="c-grid c-dash" x1="${M.left}" x2="${W - M.right}" y1="${yT(v)}" y2="${yT(v)}"/>`;
    s += `<text class="c-axis" x="${M.left - 6}" y="${yT(v) + 4}" text-anchor="end">${v}°</text>`;
  }
  for (let v = 0; v <= wMax; v += 10) {
    s += `<text class="c-axis" x="${W - M.right + 6}" y="${yW(v) + 4}">${v}</text>`;
  }
  s += `<text class="c-axis" x="${W - M.right + 6}" y="${M.top - 12}">kt</text>`;

  // Padavine
  const bw = r(step * 0.7);
  points.forEach((p, i) => {
    if (p.h === 8 || p.h === 16) s += `<text class="c-hour" x="${x(i)}" y="${M.top - 6}">${p.h}:00</text>`;
    if (p.rain < RAIN_MIN) return;
    const y = yW(p.rain);
    s += `<rect class="c-rain" x="${r(x(i) - bw / 2)}" y="${y}" width="${bw}" height="${r(bottom - y)}" rx="2"/>`;
    s += `<text class="c-rain-label" x="${x(i)}" y="${y - 5}">${p.rain > 1 ? Math.round(p.rain) : p.rain}</text>`;
  });

  // Temperatura in sunki
  const tempLine = curve(points.map((p, i) => [x(i), yT(p.temp)]));
  s += `<path fill="url(#g-temp)" d="${tempLine}L${x(n - 1)},${bottom}L${x(0)},${bottom}Z"/>`;
  s += `<path class="c-gust" d="${curve(points.map((p, i) => [x(i), yW(p.gust)]))}"/>`;
  s += `<path class="c-temp" d="${tempLine}"/>`;

  points.forEach((p, i) => {
    s += `<text class="c-icon" x="${x(i)}" y="${yT(p.temp) - 10}">${p.icon}</text>`;
    if (p.h !== 8 && p.h !== 20) return;
    // Puščica kaže, kam veter piha (meteorološka smer + 180°).
    if (p.deg != null) {
      s += `<path class="c-arrow" transform="translate(${x(i)},${bottom + 22}) rotate(${p.deg + 180})" d="M0,-11L6,0H2V11H-2V0H-6Z"/>`;
    }
    s += `<text class="c-kt" x="${x(i)}" y="${bottom + 54}">${p.gust} kt</text>`;
  });

  s += `<line class="c-guide" y1="${M.top}" y2="${bottom}" style="display:none"/>`;
  host.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img">${s}</svg><div class="chart-tip" hidden></div>`;

  // Oblaček s podatki ob premiku miške ali dotiku
  const svg = host.firstElementChild, tip = host.lastElementChild, guide = svg.querySelector(".c-guide");
  function show(e) {
    const box = svg.getBoundingClientRect();
    const sx = (e.clientX - box.left) * W / box.width;
    const i = Math.max(0, Math.min(n - 1, Math.floor((sx - M.left) / step)));
    const p = points[i], day = days[p.d];
    guide.setAttribute("x1", x(i));
    guide.setAttribute("x2", x(i));
    guide.style.display = "";
    tip.innerHTML = `<b>${day.name} ${day.date} ${p.h}:00</b><br>${p.icon} ${p.temp}°C<br>💨 ${p.gust} kt`
      + (p.deg != null ? ` ${COMPASS[Math.floor((p.deg + 11.25) / 22.5) % 16]}` : "")
      + (p.rain >= RAIN_MIN ? `<br>☔ ${p.rain} mm` : "");
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
