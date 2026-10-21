// Iskanje lokacije med tipkanjem: zadetki se pojavijo po treh znakih,
// klik (ali Enter) na zadetek izbiro takoj potrdi. Brez JS ostane navaden obrazec z gumbom Išči.
(function () {
  const input = document.getElementById("q");
  const list = document.getElementById("loc-results");
  if (!input || !list) return;
  let timer, seq = 0, shownFor = input.value.trim();

  input.addEventListener("input", () => {
    clearTimeout(timer);
    const q = input.value.trim();
    if (q.length > 0 && q.length < 3) return;
    timer = setTimeout(async () => {
      const mine = ++seq;
      try {
        const resp = await fetch("/partials/lokacije?q=" + encodeURIComponent(q));
        // Počasnejši odgovor na starejši vnos ne sme povoziti novejšega.
        if (!resp.ok || mine !== seq) return;
        list.innerHTML = await resp.text();
        shownFor = q;
      } catch (e) {
        // brez povezave: ostane zadnji seznam
      }
    }, 250);
  });

  input.addEventListener("keydown", (e) => {
    const first = list.querySelector("button");
    if (e.key === "ArrowDown" && first) {
      e.preventDefault();
      first.focus();
    } else if (e.key === "Enter" && shownFor === input.value.trim()) {
      // Enter potrdi prvi zadetek, a le če seznam že ustreza vpisanemu besedilu.
      const hit = list.querySelector("button[data-hit]");
      if (hit) {
        e.preventDefault();
        hit.click();
      }
    }
  });

  list.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    const buttons = [...list.querySelectorAll("button")];
    const i = buttons.indexOf(document.activeElement);
    if (i < 0) return;
    e.preventDefault();
    (buttons[i + (e.key === "ArrowDown" ? 1 : -1)] || input).focus();
  });
})();

// Poteg s prstom levo ali desno preklopi na sosednji zavihek. Poteg po vodoravno drsljivem delu
// (graf) najprej drsi tisti del; zavihek preklopi šele, ko je ta del že na robu v smeri potega.
(function () {
  const tabs = [...document.querySelectorAll(".tabs a[data-swipe]")];
  const current = tabs.findIndex((a) => a.classList.contains("active"));
  if (current < 0) return;
  const EDGE = 24;  // rob zaslona pustimo sistemski kretnji "nazaj"
  let start = null;

  // Ali ima kateri od drsljivih prednikov dotaknjenega elementa še kaj vsebine levo oziroma desno.
  function scrollRoom(el) {
    const room = { left: false, right: false };
    for (; el && el !== document.body; el = el.parentElement) {
      const max = el.scrollWidth - el.clientWidth;
      if (max > 1 && /auto|scroll/.test(getComputedStyle(el).overflowX)) {
        if (el.scrollLeft > 1) room.left = true;
        if (el.scrollLeft < max - 1) room.right = true;
      }
    }
    return room;
  }

  document.addEventListener("touchstart", (e) => {
    const p = e.touches[0];
    // Stran lahko poteg začasno izklopi (straža sidra med delovanjem).
    const usable = e.touches.length === 1 && p.clientX > EDGE && p.clientX < innerWidth - EDGE
      && !("noSwipe" in document.body.dataset);
    start = usable ? { x: p.clientX, y: p.clientY, at: Date.now(), room: scrollRoom(e.target) } : null;
  }, { passive: true });

  document.addEventListener("touchend", (e) => {
    if (!start) return;
    const p = e.changedTouches[0];
    const dx = p.clientX - start.x, dy = p.clientY - start.y, quick = Date.now() - start.at < 700;
    const scrolls = dx < 0 ? start.room.right : start.room.left;
    start = null;
    if (scrolls || !quick || Math.abs(dx) < 60 || Math.abs(dx) < 2 * Math.abs(dy)) return;
    const target = tabs[current + (dx < 0 ? 1 : -1)];
    if (!target) return;
    try { sessionStorage.setItem("swipe", dx < 0 ? "swipe-next" : "swipe-prev"); } catch (_) {}
    location.href = target.href;
  }, { passive: true });
})();

// Delni izrisi: element z data-src naloži svojo vsebino s strežnika,
// z data-every (sekunde) pa jo tudi periodično osvežuje.
document.querySelectorAll("[data-src]").forEach((el) => {
  const every = Number(el.dataset.every || 0) * 1000;
  let last = "loaded" in el.dataset ? Date.now() : 0;

  async function load() {
    last = Date.now();
    let ok = false;
    try {
      const resp = await fetch(el.dataset.src);
      ok = resp.ok;
      if (ok) el.innerHTML = await resp.text();
    } catch (e) {
      // brez povezave
    }
    // Ob napaki ostane zadnja znana vsebina; samo začetni "nalagam" se zamenja s sporočilom.
    const waiting = el.querySelector(".thinking");
    if (!ok && waiting && el.dataset.fail) {
      waiting.classList.remove("thinking");
      waiting.textContent = el.dataset.fail;
    }
  }

  if (!last) load();
  if (every) {
    setInterval(() => { if (!document.hidden) load(); }, every);
    // Ko se telefon zbudi ali se zavihek vrne v ospredje, takoj nadoknadi zamujeno osvežitev.
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden && Date.now() - last > every) load();
    });
  }
});
