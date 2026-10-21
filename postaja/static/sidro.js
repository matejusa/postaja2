// Straža sidra: ob Startu si zapomni položaj (sidro), nato z GPS-om telefona spremlja oddaljenost,
// riše sled in sproži alarm, ko je plovilo več zaporednih meritev zunaj nastavljenega kroga.
// GPS se vklopi že ob odprtju strani, da je ob Startu umirjen. Vse teče v brskalniku; položaj se nikamor ne pošilja.
(function () {
  if (!document.getElementById("anchor")) return;
  const T = JSON.parse(document.getElementById("anchor-texts").textContent);
  const $ = (id) => document.getElementById(id);

  const GOOD_FIX_M = 25;        // za položaj sidra štejejo samo meritve vsaj te natančnosti
  const WARMUP_S = 8;           // prve sekunde po vklopu GPS položaj še skače, zato jih ne uporabimo za sidro
  const FRESH_S = 5;            // položaj sidra je povprečje dobrih meritev zadnjih toliko sekund
  const FIRST_FIX_WAIT_S = 15;  // če se GPS po Startu ne umiri, po tem času sprejmemo najboljšo dotedanjo meritev
  const USABLE_FIX_M = 50;      // slabših meritev ne upoštevamo za razdaljo, sled in alarm
  const ALARM_FIXES = 3;        // toliko zaporednih meritev zunaj kroga sproži alarm
  const STALE_S = 30;           // po toliko sekundah brez meritve opozorimo na zastarel položaj
  const TRACK_STEP_M = 2, TRACK_MAX = 1500;
  const RADIUS_MIN = 10, RADIUS_MAX = 300, RADIUS_STEP = 5;

  const read = (key) => { try { return JSON.parse(localStorage.getItem(key)); } catch (_) { return null; } };
  const write = (key, value) => {
    try { value === null ? localStorage.removeItem(key) : localStorage.setItem(key, JSON.stringify(value)); } catch (_) {}
  };
  const r1 = (v) => Math.round(v * 10) / 10;
  const mean = (values) => values.reduce((sum, v) => sum + v, 0) / values.length;

  const prefs = Object.assign({ radius: 40, alarm: true }, read("sidro-nastavitve"));
  let watch = read("sidro");  // straža v teku: { lat, lon, t0, track: [[x, y], …], max }; preživi osvežitev strani
  let waiting = null;         // po Startu, dokler GPS ni umirjen: { since, best }
  let fix = null;             // zadnja uporabna meritev: { x, y, acc, dist, at } v metrih od sidra
  let recent = [];            // meritve zadnjih FRESH_S sekund: { lat, lon, acc, at }
  let firstFixAt = null;      // kdaj je GPS po vklopu dal prvo meritev
  let lastAcc = null, message = null;
  let outside = 0, alarm = "ok";  // "ok" | "on" (zvoni) | "muted" (zunaj kroga, utišan)
  let geoId = null, siren = null, wakeLock = null, audio = null;

  const active = () => !!(watch || waiting);

  // ── Zvok in vibriranje ──
  function sound() {
    if (!audio) {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return null;
      audio = new Ctx();
      // iPhone: brez tega stikalo za tihi način utiša tudi alarm.
      try { if (navigator.audioSession) navigator.audioSession.type = "playback"; } catch (_) {}
    }
    if (audio.state === "suspended") audio.resume().then(render, () => {});
    return audio;
  }

  function beep() {
    if (navigator.vibrate) navigator.vibrate([250, 100, 250]);
    const ctx = sound();
    if (!ctx || ctx.state !== "running") return;
    [880, 660].forEach((freq, i) => {
      const osc = ctx.createOscillator(), gain = ctx.createGain();
      osc.type = "square";
      osc.frequency.value = freq;
      gain.gain.value = 0.6;
      osc.connect(gain).connect(ctx.destination);
      osc.start(ctx.currentTime + i * 0.25);
      osc.stop(ctx.currentTime + i * 0.25 + 0.22);
    });
  }

  function setAlarm(state) {
    if (state === alarm) return;
    alarm = state;
    clearInterval(siren);
    siren = null;
    if (state === "on") {
      beep();
      siren = setInterval(beep, 800);
    } else if (navigator.vibrate) {
      navigator.vibrate(0);
    }
  }

  // ── Zaslon naj ostane prižgan, dokler straža teče ──
  async function keepAwake() {
    let held = false;
    try {
      if ("wakeLock" in navigator) {
        wakeLock = await navigator.wakeLock.request("screen");
        held = true;
      }
    } catch (_) {}
    $("a-wake").textContent = held ? T.wake_on : T.wake_off;
  }

  // ── GPS ──
  function listen() {
    if (geoId !== null || !navigator.geolocation) return;
    recent = [];
    firstFixAt = null;
    geoId = navigator.geolocation.watchPosition(onFix, onError, { enableHighAccuracy: true, maximumAge: 0, timeout: 30000 });
  }

  function unlisten() {
    if (geoId !== null) navigator.geolocation.clearWatch(geoId);
    geoId = null;
  }

  // Umirjen položaj: povprečje svežih dobrih meritev, a šele ko GPS teče dovolj dolgo.
  function settled() {
    const now = Date.now();
    if (firstFixAt === null || now - firstFixAt < WARMUP_S * 1000) return null;
    const good = recent.filter((f) => now - f.at <= FRESH_S * 1000 && f.acc <= GOOD_FIX_M);
    if (!good.length) return null;
    return { lat: mean(good.map((f) => f.lat)), lon: mean(good.map((f) => f.lon)) };
  }

  // ── Potek straže ──
  function start() {
    message = null;
    if (!navigator.geolocation) {
      message = T.unsupported;
      return render();
    }
    sound();  // dotik na Start brskalniku dovoli kasnejši zvok alarma
    const spot = settled();
    if (spot) {
      // GPS je že umirjen: sidro postavimo takoj in prikažemo zadnjo meritev, ne da bi čakali naslednjo.
      setAnchor(spot, Date.now());
      const last = recent[recent.length - 1];
      place(last.lat, last.lon, last.acc, last.at);
    } else {
      waiting = { since: Date.now(), best: null };
    }
    begin();
  }

  function setAnchor(spot, since) {
    watch = { lat: spot.lat, lon: spot.lon, t0: since, track: [[0, 0]], max: 0 };
    waiting = null;
    write("sidro", watch);
  }

  // Skupno za Start in za nadaljevanje straže po osvežitvi strani.
  function begin() {
    listen();
    document.body.dataset.noSwipe = "";  // poteg med zavihki bi stražo prekinil
    keepAwake();
    render();
  }

  // GPS po koncu straže ostane vklopljen, da je za naslednji Start že umirjen.
  function stop() {
    setAlarm("ok");
    watch = waiting = fix = null;
    outside = 0;
    write("sidro", null);
    delete document.body.dataset.noSwipe;
    if (wakeLock) wakeLock.release().catch(() => {});
    wakeLock = null;
    $("a-wake").textContent = "";
    render();
  }

  function onFix(p) {
    const { latitude: lat, longitude: lon, accuracy: acc } = p.coords;
    const now = Date.now();
    lastAcc = acc;
    if (firstFixAt === null) firstFixAt = now;
    recent = recent.filter((f) => now - f.at <= FRESH_S * 1000);
    recent.push({ lat, lon, acc, at: now });

    if (!watch) {
      if (!waiting) return render();
      if (!waiting.best || acc < waiting.best.acc) waiting.best = { lat, lon, acc };
      const spot = settled() || (now - waiting.since >= FIRST_FIX_WAIT_S * 1000 ? waiting.best : null);
      if (!spot) return render();
      setAnchor(spot, waiting.since);
    }
    place(lat, lon, acc, now);
    render();
  }

  // Meritev preračuna v metre od sidra, podaljša sled in preveri alarm.
  function place(lat, lon, acc, now) {
    if (acc > USABLE_FIX_M) return;

    // Na razdaljah nekaj sto metrov zadošča ravninski približek.
    const x = (lon - watch.lon) * 111320 * Math.cos(watch.lat * Math.PI / 180);
    const y = (lat - watch.lat) * 110540;
    const dist = Math.hypot(x, y);
    fix = { x, y, acc, dist, at: now };

    let changed = false;
    const last = watch.track[watch.track.length - 1];
    if (Math.hypot(x - last[0], y - last[1]) >= TRACK_STEP_M) {
      watch.track.push([r1(x), r1(y)]);
      // Predolgo sled razredčimo, da risanje in shranjevanje ostaneta hitra.
      if (watch.track.length > TRACK_MAX) watch.track = watch.track.filter((_, i, all) => i % 2 === 0 || i === all.length - 1);
      changed = true;
    }
    if (dist > watch.max) {
      watch.max = r1(dist);
      changed = true;
    }
    if (changed) write("sidro", watch);
    check();
  }

  // Alarm se sproži po več zaporednih meritvah zunaj kroga in se znova pripravi, ko je plovilo spet znotraj.
  function check() {
    if (!fix) return;
    outside = fix.dist > prefs.radius ? outside + 1 : 0;
    if (!outside) setAlarm("ok");
    else if (!prefs.alarm) setAlarm("muted");
    else if (alarm === "ok" && outside >= ALARM_FIXES) setAlarm("on");
  }

  function onError(e) {
    if (e.code !== 1) return;  // začasna izguba signala: opozori prikaz zastarele meritve
    // Zavrnjen dostop do lokacije. Že postavljeno sidro obdržimo, da ga napačen dotik pri vprašanju
    // brskalnika ne izbriše; naslednji dotik zaslona poskusi znova.
    unlisten();
    if (waiting) stop();
    message = T.denied;
    render();
  }

  // ── Prikaz ──
  function clock(ms) {
    const s = Math.max(0, Math.floor(ms / 1000));
    const two = (v) => String(v).padStart(2, "0");
    return `${Math.floor(s / 3600)}:${two(Math.floor(s / 60) % 60)}:${two(s % 60)}`;
  }

  function gpsState() {
    if (geoId === null) return "";
    if (settled()) return `${T.gps_ready} (±${Math.round(lastAcc)} m). `;
    return `${firstFixAt === null ? T.waiting : T.gps_settling} `;
  }

  function render() {
    const on = active();
    const stale = on && fix && Date.now() - fix.at > STALE_S * 1000;
    $("a-start").hidden = on;
    $("a-stop").hidden = !on;
    $("a-dist").textContent = fix ? Math.round(fix.dist) : on ? "–" : 0;
    $("a-time").textContent = clock(watch ? Date.now() - watch.t0 : waiting ? Date.now() - waiting.since : 0);
    $("a-acc").textContent = geoId !== null && lastAcc !== null ? `±${Math.round(lastAcc)} m` : "–";
    $("a-max").textContent = `${watch ? Math.round(watch.max) : 0} m`;
    $("a-radius").textContent = prefs.radius;
    $("a-on").checked = prefs.alarm;

    let text = gpsState() + T.idle, kind = "";
    if (message) [text, kind] = [message, "warn"];
    else if (on && !fix) [text, kind] = [firstFixAt === null ? T.waiting : T.gps_settling, "note"];
    else if (alarm === "on") [text, kind] = [T.alarm_text, "warn"];
    else if (outside) [text, kind] = [T.outside, "warn"];
    else if (stale) [text, kind] = [`${T.stale} (${Math.round((Date.now() - fix.at) / 1000)} s)`, "note"];
    else if (on) [text, kind] = [T.watching, "ok"];
    $("a-status").textContent = text;
    $("a-status").className = `a-status ${kind}`;

    $("a-overlay").hidden = alarm !== "on";
    $("a-overlay-dist").textContent = fix ? `${Math.round(fix.dist)} m` : "";
    $("a-hint").hidden = !(on && prefs.alarm && (!audio || audio.state !== "running"));
    draw();
  }

  // Risba: sever je zgoraj, sidro v središču, merilo se prilagaja najdaljši razdalji.
  function draw() {
    const reach = Math.max(prefs.radius, watch ? watch.max : 0, fix ? fix.dist : 0);
    const k = 88 / reach;  // metri → enote risbe (viewBox sega do ±100)
    let s = `<circle class="a-ring${prefs.alarm ? "" : " off"}" r="${r1(prefs.radius * k)}"/>`;
    s += `<text class="a-label" y="${r1(-prefs.radius * k - 3)}">${prefs.radius} m</text>`;
    s += `<text class="a-label" x="-90" y="-88">${T.north} ↑</text>`;
    if (watch) {
      const points = watch.track.concat(fix ? [[fix.x, fix.y]] : []);
      s += `<polyline class="a-track" points="${points.map(([x, y]) => `${r1(x * k)},${r1(-y * k)}`).join(" ")}"/>`;
    }
    s += `<text class="a-anchor" y="5">⚓</text>`;
    if (fix) {
      s += `<circle class="a-acc" cx="${r1(fix.x * k)}" cy="${r1(-fix.y * k)}" r="${r1(fix.acc * k)}"/>`;
      s += `<circle class="a-boat" cx="${r1(fix.x * k)}" cy="${r1(-fix.y * k)}" r="4"/>`;
    }
    $("a-plot").innerHTML = s;
  }

  // ── Upravljanje ──
  function savePrefs() {
    write("sidro-nastavitve", prefs);
    if (fix) {
      outside = fix.dist > prefs.radius ? Math.max(outside, 1) : 0;
      if (!outside) setAlarm("ok");
      else if (!prefs.alarm) setAlarm("muted");
    }
    render();
  }

  function changeRadius(step) {
    prefs.radius = Math.min(RADIUS_MAX, Math.max(RADIUS_MIN, prefs.radius + step));
    savePrefs();
  }

  $("a-start").addEventListener("click", start);
  $("a-stop").addEventListener("click", () => {
    if (!confirm(T.stop_confirm)) return;
    message = null;
    stop();
  });
  $("a-minus").addEventListener("click", () => changeRadius(-RADIUS_STEP));
  $("a-plus").addEventListener("click", () => changeRadius(RADIUS_STEP));
  $("a-on").addEventListener("change", (e) => {
    prefs.alarm = e.target.checked;
    // Vklop alarma, ko je plovilo že zunaj kroga, ga mora sprožiti takoj.
    if (prefs.alarm && alarm === "muted" && outside >= ALARM_FIXES) setAlarm("on");
    savePrefs();
  });
  $("a-mute").addEventListener("click", () => { setAlarm(outside ? "muted" : "ok"); render(); });
  $("a-test").addEventListener("click", () => {
    sound();
    [0, 800, 1600].forEach((delay) => setTimeout(beep, delay));
  });

  document.addEventListener("pointerdown", () => {
    // Brskalnik dovoli zvok šele po dotiku; po osvežitvi strani ga zato vklopi prvi dotik kjerkoli.
    if (active()) sound();
    // Po zavrnjenem dostopu do lokacije dotik poskusi znova.
    if (geoId === null && navigator.geolocation) {
      message = null;
      listen();
    }
  });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      if (!active()) unlisten();  // v pripravljenosti GPS v ozadju ne prazni baterije
    } else {
      listen();
      if (active()) keepAwake();
    }
  });
  // Na drugi strani straža ne teče, zato pred odhodom vprašamo.
  document.addEventListener("click", (e) => {
    if (active() && e.target.closest("a[href]") && !confirm(T.leave_confirm)) e.preventDefault();
  });

  setInterval(render, 1000);
  if (watch && !navigator.geolocation) watch = null;
  if (watch) {
    begin();
  } else {
    listen();
    render();
  }
})();
