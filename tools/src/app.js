(() => {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const root = document.documentElement;
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* storage unavailable */ } },
  };
  const css = (name, el = root) => getComputedStyle(el).getPropertyValue(name).trim();
  const themeListeners = [];
  const onTheme = (fn) => themeListeners.push(fn);
  const fireTheme = () => themeListeners.forEach((f) => f());

  /* ---------------- theme ---------------- */
  const saved = store.get("thesis-theme");
  if (saved === "dark" || saved === "light") root.setAttribute("data-theme", saved);
  const isDark = () => {
    const t = root.getAttribute("data-theme");
    if (t) return t === "dark";
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  };
  $("#themeBtn").addEventListener("click", () => {
    const next = isDark() ? "light" : "dark";
    root.setAttribute("data-theme", next);
    store.set("thesis-theme", next);
    fireTheme();
  });
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", fireTheme);
  new MutationObserver(fireTheme).observe(root, { attributes: true, attributeFilter: ["data-theme"] });

  /* ---------------- hero: animated isodose field ---------------- */
  (function hero() {
    const cv = $("#dose");
    if (!cv) return;
    const hero = $(".hero");
    const ctx = cv.getContext("2d");
    const levels = [0.2, 0.35, 0.5, 0.65, 0.8, 0.95];
    const colors = ["--h1", "--h2", "--h3", "--h4", "--h5", "--h6"].map((v) => css(v));
    let W = 0, H = 0, dpr = 1, step = 12, cols = 0, rows = 0, vals = null;
    let running = false, visible = true, t0 = performance.now();
    const ptr = { x: 0, y: 0, a: 0, ta: 0 };
    const blobs = [
      { ox: 0.70, oy: 0.46, rx: 0.06, ry: 0.05, sx: 0.13, sy: 0.16, a: 1.0, sp: 0.00021, ph: 0.0 },
      { ox: 0.62, oy: 0.58, rx: 0.05, ry: 0.04, sx: 0.08, sy: 0.07, a: 0.75, sp: 0.00033, ph: 1.7 },
      { ox: 0.80, oy: 0.60, rx: 0.04, ry: 0.06, sx: 0.07, sy: 0.08, a: 0.7, sp: 0.00027, ph: 3.1 },
      { ox: 0.76, oy: 0.33, rx: 0.05, ry: 0.03, sx: 0.06, sy: 0.05, a: 0.55, sp: 0.00041, ph: 4.4 },
      { ox: 0.88, oy: 0.44, rx: 0.03, ry: 0.05, sx: 0.05, sy: 0.09, a: 0.5, sp: 0.00037, ph: 5.2 },
    ];

    function resize() {
      const r = hero.getBoundingClientRect();
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      W = r.width; H = r.height;
      cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
      step = W < 700 ? 9 : 12;
      cols = Math.ceil(W / step) + 1; rows = Math.ceil(H / step) + 1;
      vals = new Float32Array(cols * rows);
      if (!running) frame(performance.now());
    }

    function field(t) {
      const mobile = W < 860;
      const cx = mobile ? 0.62 : 0.74, cy = mobile ? 0.62 : 0.52;
      const bodyRx = mobile ? 0.55 * W : Math.min(0.30 * W, 0.62 * H), bodyRy = mobile ? 0.38 * H : 0.42 * H;
      const bcx = cx * W, bcy = cy * H;
      const bl = blobs.map((b) => {
        const k = t * b.sp + b.ph;
        return {
          x: ((mobile ? b.ox - 0.12 : b.ox) + b.rx * Math.cos(k)) * W,
          y: ((mobile ? b.oy + 0.12 : b.oy) + b.ry * Math.sin(k * 1.3)) * H,
          sx2: Math.pow(b.sx * Math.min(W, 1.6 * H), 2), sy2: Math.pow(b.sy * H, 2), a: b.a,
        };
      });
      const ps2 = Math.pow(Math.min(W, H) * 0.08, 2);
      for (let j = 0; j < rows; j++) {
        const y = j * step;
        for (let i = 0; i < cols; i++) {
          const x = i * step;
          let v = 0;
          for (let n = 0; n < bl.length; n++) {
            const b = bl[n];
            const dx = x - b.x, dy = y - b.y;
            v += b.a * Math.exp(-(dx * dx) / b.sx2 - (dy * dy) / b.sy2);
          }
          if (ptr.a > 0.01) {
            const dx = x - ptr.x, dy = y - ptr.y;
            v += 0.85 * ptr.a * Math.exp(-(dx * dx + dy * dy) / ps2);
          }
          // soft body outline: dose falls off outside the patient
          const ex = (x - bcx) / bodyRx, ey = (y - bcy) / bodyRy;
          const e = ex * ex + ey * ey;
          const m = e < 1 ? 1 : Math.exp(-(e - 1) * 6);
          vals[j * cols + i] = Math.min(v, 1.15) * m;
        }
      }
      return { bcx, bcy, bodyRx, bodyRy };
    }

    function contour(level) {
      ctx.beginPath();
      for (let j = 0; j < rows - 1; j++) {
        for (let i = 0; i < cols - 1; i++) {
          const a = vals[j * cols + i], b = vals[j * cols + i + 1], c = vals[(j + 1) * cols + i + 1], d = vals[(j + 1) * cols + i];
          let idx = 0;
          if (a > level) idx |= 8; if (b > level) idx |= 4; if (c > level) idx |= 2; if (d > level) idx |= 1;
          if (idx === 0 || idx === 15) continue;
          const x = i * step, y = j * step;
          const top = [x + step * (level - a) / (b - a), y];
          const right = [x + step, y + step * (level - b) / (c - b)];
          const bottom = [x + step * (level - d) / (c - d), y + step];
          const left = [x, y + step * (level - a) / (d - a)];
          const seg = (p, q) => { ctx.moveTo(p[0], p[1]); ctx.lineTo(q[0], q[1]); };
          switch (idx) {
            case 1: case 14: seg(left, bottom); break;
            case 2: case 13: seg(bottom, right); break;
            case 3: case 12: seg(left, right); break;
            case 4: case 11: seg(top, right); break;
            case 5: seg(left, top); seg(bottom, right); break;
            case 6: case 9: seg(top, bottom); break;
            case 7: case 8: seg(left, top); break;
            case 10: seg(left, bottom); seg(top, right); break;
          }
        }
      }
      ctx.stroke();
    }

    function frame(now) {
      const t = reduce ? 0 : now - t0;
      ptr.a += (ptr.ta - ptr.a) * 0.08;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, W, H);
      const g = field(t);
      // gantry ring + body outline + crosshair
      ctx.lineWidth = 1;
      ctx.strokeStyle = "rgba(125,139,160,0.20)";
      ctx.beginPath(); ctx.ellipse(g.bcx, g.bcy, g.bodyRx, g.bodyRy, 0, 0, Math.PI * 2); ctx.stroke();
      const R = Math.max(g.bodyRx, g.bodyRy) * 1.22;
      ctx.strokeStyle = "rgba(125,139,160,0.12)";
      ctx.beginPath(); ctx.arc(g.bcx, g.bcy, R, 0, Math.PI * 2); ctx.stroke();
      ctx.beginPath();
      for (let k = 0; k < 72; k++) {
        const an = (k / 72) * Math.PI * 2, l = k % 9 === 0 ? 10 : 4;
        ctx.moveTo(g.bcx + Math.cos(an) * R, g.bcy + Math.sin(an) * R);
        ctx.lineTo(g.bcx + Math.cos(an) * (R - l), g.bcy + Math.sin(an) * (R - l));
      }
      ctx.stroke();
      ctx.setLineDash([2, 6]);
      ctx.beginPath(); ctx.moveTo(g.bcx - R, g.bcy); ctx.lineTo(g.bcx + R, g.bcy); ctx.moveTo(g.bcx, g.bcy - R); ctx.lineTo(g.bcx, g.bcy + R); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = "rgba(125,139,160,0.55)";
      ctx.font = "500 11px 'Google Sans Code', ui-monospace, monospace";
      ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillText("A", g.bcx, g.bcy - R - 12); ctx.fillText("P", g.bcx, g.bcy + R + 12);
      ctx.fillText("R", g.bcx - R - 12, g.bcy); ctx.fillText("L", g.bcx + R + 12, g.bcy);
      // isodose lines
      ctx.lineJoin = "round"; ctx.lineCap = "round";
      levels.forEach((lv, k) => {
        ctx.strokeStyle = colors[k];
        ctx.globalAlpha = 0.5 + k * 0.09;
        ctx.lineWidth = k === levels.length - 1 ? 2 : 1.3;
        if (k === levels.length - 1) { ctx.shadowColor = colors[k]; ctx.shadowBlur = 12; }
        contour(lv);
        ctx.shadowBlur = 0;
      });
      ctx.globalAlpha = 1;
      if (running) requestAnimationFrame(frame);
    }

    function start() { if (running || reduce || !visible || document.hidden) return; running = true; requestAnimationFrame(frame); }
    function stop() { running = false; }
    new IntersectionObserver((es) => { visible = es[0].isIntersecting; visible ? start() : stop(); }).observe(hero);
    document.addEventListener("visibilitychange", () => (document.hidden ? stop() : start()));
    hero.addEventListener("pointermove", (e) => {
      const r = hero.getBoundingClientRect();
      ptr.x = e.clientX - r.left; ptr.y = e.clientY - r.top; ptr.ta = 1;
      if (reduce) frame(0);
    });
    hero.addEventListener("pointerleave", () => { ptr.ta = 0; if (reduce) { ptr.a = 0; frame(0); } });
    new ResizeObserver(resize).observe(hero);
    resize();
    start();
  })();

  /* ---------------- HUD, progress, scrollspy ---------------- */
  const hud = $("#hud"), bar = $("#hudBar"), hudCh = $("#hudCh"), hudSec = $("#hudSec"), hudSlice = $("#hudSlice");
  const heroEl = $(".hero");
  const slices = $$(".prose > p, .abstract > p");
  const totalSlices = slices.length;
  const pad = (n) => String(n).padStart(4, "0");

  const sections = $$(".front, .cohort, .chapter, .back, .colophon");
  const heads = $$(".prose h2[id], .prose h3[id]");
  const railLinks = new Map($$(".rail a[data-target]").map((a) => [a.dataset.target, a]));

  let ticking = false;
  function onScroll() {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(() => {
      ticking = false;
      const y = window.scrollY, vh = window.innerHeight;
      const max = document.documentElement.scrollHeight - vh;
      bar.style.transform = `scaleX(${max > 0 ? Math.min(1, y / max) : 0})`;
      hud.classList.toggle("on-hero", heroEl.getBoundingClientRect().bottom > 60);
      // reading position as a slice index
      const probe = vh * 0.35;
      let lo = 0, hi = totalSlices - 1, idx = 0;
      while (lo <= hi) { const mid = (lo + hi) >> 1; if (slices[mid].getBoundingClientRect().top < probe) { idx = mid; lo = mid + 1; } else hi = mid - 1; }
      hudSlice.textContent = `SL ${pad(idx + 1)}/${pad(totalSlices)}`;
      // current section
      let cur = null;
      for (const s of sections) { if (s.getBoundingClientRect().top < probe) cur = s; else break; }
      let sec = null;
      for (const h of heads) { if (h.getBoundingClientRect().top < probe) sec = h; else break; }
      updateLoc(cur, sec && cur && cur.contains(sec) ? sec : null);
    });
  }
  let lastKey = "";
  function updateLoc(cur, sec) {
    const key = (cur ? cur.id : "") + "|" + (sec ? sec.id : "");
    if (key === lastKey) return;
    lastKey = key;
    const ch = cur && cur.dataset.ch;
    root.style.setProperty("--cur", ch ? `var(--c${ch})` : "var(--c1)");
    hudCh.textContent = !cur ? "Overview" : ch ? `Ch ${ch}` : cur.dataset.short || "";
    hudSec.textContent = sec ? [".h-num", ".h-title"].map((q) => (sec.querySelector(q) || {}).textContent || "").join("  ").trim() : ch ? cur.dataset.short : "";
    railLinks.forEach((a) => a.classList.remove("active"));
    $$(".rail-ch").forEach((li) => li.classList.remove("open"));
    if (cur && railLinks.get(cur.id)) {
      const a = railLinks.get(cur.id);
      a.classList.add("active");
      const li = a.closest(".rail-ch");
      if (li) li.classList.add("open");
    }
    if (sec) {
      // nearest h2 for h3s
      let h = sec;
      while (h && !railLinks.get(h.id)) { h = prevHeading(h); }
      if (h) {
        const a = railLinks.get(h.id);
        a.classList.add("active");
        const rail = $("#rail");
        if (window.innerWidth >= 1200) {
          const ar = a.getBoundingClientRect(), rr = rail.getBoundingClientRect();
          if (ar.top < rr.top + 40 || ar.bottom > rr.bottom - 40) rail.scrollTo({ top: rail.scrollTop + ar.top - rr.top - rr.height / 3, behavior: reduce ? "auto" : "smooth" });
        }
      }
    }
  }
  function prevHeading(h) {
    const i = heads.indexOf(h);
    for (let k = i - 1; k >= 0; k--) if (heads[k].tagName === "H2") return heads[k];
    return null;
  }
  window.addEventListener("scroll", onScroll, { passive: true });
  window.addEventListener("resize", onScroll);
  onScroll();

  /* ---------------- contents drawer ---------------- */
  const rail = $("#rail"), scrim = $("#scrim"), tocBtn = $("#tocBtn");
  function openRail(o) {
    rail.classList.toggle("open", o);
    scrim.hidden = !o;
    tocBtn.setAttribute("aria-expanded", String(o));
    if (o) $(".rail a", rail).focus({ preventScroll: true });
  }
  tocBtn.addEventListener("click", () => {
    if (window.innerWidth >= 1200) { rail.scrollTo({ top: 0, behavior: "smooth" }); $(".rail a", rail).focus(); return; }
    openRail(!rail.classList.contains("open"));
  });
  $("#railClose").addEventListener("click", () => openRail(false));
  scrim.addEventListener("click", () => openRail(false));
  rail.addEventListener("click", (e) => { if (e.target.closest("a") && window.innerWidth < 1200) openRail(false); });

  /* ---------------- lightbox ---------------- */
  const lb = $("#lb"), stage = $("#lbStage"), lbCap = $("#lbCap"), lbLabel = $("#lbLabel"), lbCount = $("#lbCount");
  const figs = $$("figure.fig");
  let cur = -1, lastFocus = null;
  function show(i) {
    cur = (i + figs.length) % figs.length;
    const f = figs[cur];
    stage.innerHTML = "";
    const wrap = document.createElement("div");
    wrap.className = "lb-imgs";
    $$("img", f).forEach((im) => {
      const n = document.createElement("img");
      n.src = im.getAttribute("src"); n.alt = ""; n.width = im.width; n.height = im.height;
      n.addEventListener("click", () => lb.classList.toggle("zoomed"));
      wrap.appendChild(n);
    });
    stage.appendChild(wrap);
    const lab = $(".fig-label", f), txt = $(".fig-text", f);
    lbLabel.textContent = lab ? lab.textContent : "Figure";
    lbCap.innerHTML = txt ? txt.innerHTML : "";
    lbCount.textContent = `${cur + 1} / ${figs.length}`;
    lb.classList.remove("zoomed");
    stage.scrollTo(0, 0);
  }
  function openLb(i) {
    lastFocus = document.activeElement;
    show(i);
    lb.hidden = false;
    document.body.style.overflow = "hidden";
    $("#lbClose").focus();
  }
  function closeLb() {
    lb.hidden = true;
    document.body.style.overflow = "";
    if (lastFocus) lastFocus.focus({ preventScroll: true });
  }
  figs.forEach((f, i) => $(".fig-zoom", f).addEventListener("click", () => openLb(i)));
  $("#lbClose").addEventListener("click", closeLb);
  $("#lbPrev").addEventListener("click", () => show(cur - 1));
  $("#lbNext").addEventListener("click", () => show(cur + 1));
  $("#lbZoom").addEventListener("click", () => lb.classList.toggle("zoomed"));
  lbCap.addEventListener("click", (e) => { if (e.target.closest("a")) closeLb(); });
  document.addEventListener("keydown", (e) => {
    if (!lb.hidden) {
      if (e.key === "Escape") closeLb();
      else if (e.key === "ArrowRight") show(cur + 1);
      else if (e.key === "ArrowLeft") show(cur - 1);
      else if (e.key === "Tab") {
        const f = $$("button", lb);
        if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
        else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
      }
    } else if (e.key === "Escape") { hidePop(); openRail(false); }
  });
  window.openFigure = (id) => { const i = figs.findIndex((f) => f.id === id); if (i >= 0) openLb(i); };

  /* ---------------- citation popovers ---------------- */
  let refs = {};
  try { refs = JSON.parse($("#refData").textContent); } catch (e) { refs = {}; }
  const pop = $("#pop");
  let popFor = null, hideT = 0;
  function showPop(a) {
    const r = refs[a.dataset.ref];
    if (!r) return;
    clearTimeout(hideT);
    if (popFor) popFor.classList.remove("on");
    popFor = a; a.classList.add("on");
    pop.innerHTML = `<div class="pop-k">${r.k}<span>[${r.n}]</span></div><div class="pop-b">${r.h}</div><a class="pop-go" href="#${a.dataset.ref}">Go to reference →</a>`;
    pop.hidden = false;
    const ar = a.getBoundingClientRect();
    const pw = pop.offsetWidth, ph = pop.offsetHeight;
    let left = ar.left + window.scrollX + ar.width / 2 - pw / 2;
    left = Math.max(window.scrollX + 16, Math.min(left, window.scrollX + document.documentElement.clientWidth - pw - 16));
    let top = ar.bottom + window.scrollY + 8;
    if (ar.bottom + ph + 16 > window.innerHeight && ar.top > ph + 80) top = ar.top + window.scrollY - ph - 8;
    pop.style.left = `${left}px`; pop.style.top = `${top}px`;
  }
  function hidePop() { pop.hidden = true; if (popFor) popFor.classList.remove("on"); popFor = null; }
  const hover = window.matchMedia("(hover: hover)").matches;
  document.addEventListener("click", (e) => {
    const a = e.target.closest("a.cite");
    if (a && !lb.contains(a)) {
      if (!hover || popFor !== a) { e.preventDefault(); showPop(a); return; }
    }
    const go = e.target.closest(".pop-go");
    if (go) { const id = go.getAttribute("href").slice(1); hidePop(); flash(id); return; }
    if (!e.target.closest("#pop")) hidePop();
  });
  if (hover) {
    document.addEventListener("mouseover", (e) => {
      const a = e.target.closest("a.cite");
      if (a && !lb.contains(a)) showPop(a);
      else if (e.target.closest("#pop")) clearTimeout(hideT);
    });
    document.addEventListener("mouseout", (e) => {
      if (e.target.closest("a.cite") || e.target.closest("#pop")) { clearTimeout(hideT); hideT = setTimeout(hidePop, 220); }
    });
  }
  document.addEventListener("focusin", (e) => { const a = e.target.closest && e.target.closest("a.cite"); if (a) showPop(a); });
  window.addEventListener("resize", hidePop);
  function flash(id) {
    const el = document.getElementById(id);
    if (!el) return;
    el.classList.add("flash");
    setTimeout(() => el.classList.remove("flash"), 1800);
  }

  /* ---------------- references filter ---------------- */
  const filter = $("#refFilter"), refCount = $("#refCount");
  const refItems = $$(".refs li");
  function runFilter() {
    const q = filter.value.trim().toLowerCase();
    let n = 0;
    refItems.forEach((li) => { const hit = !q || li.textContent.toLowerCase().includes(q); li.hidden = !hit; if (hit) n++; });
    refCount.textContent = q ? `${n} of ${refItems.length}` : `${refItems.length} total`;
  }
  filter.addEventListener("input", runFilter);
  runFilter();

  /* ---------------- copy BibTeX ---------------- */
  const copyBtn = $("#copyBib");
  copyBtn.addEventListener("click", () => {
    const text = $("#bib").textContent;
    const done = (ok) => { copyBtn.textContent = ok ? "Copied" : "Selected, press Ctrl+C"; setTimeout(() => (copyBtn.textContent = "Copy BibTeX"), 2000); };
    const select = () => { const r = document.createRange(); r.selectNodeContents($("#bib")); const s = getSelection(); s.removeAllRanges(); s.addRange(r); done(false); };
    try { navigator.clipboard.writeText(text).then(() => done(true), select); } catch (e) { select(); }
  });

  /* ---------------- cohort waffle ---------------- */
  (function cohort() {
    const cv = $("#waffle");
    if (!cv) return;
    const ctx = cv.getContext("2d");
    const btns = $$(".cohort-list button");
    const N = 3346;
    let n = N, shown = N, color = "--c2", raf = 0;
    btns.forEach((b) => b.style.setProperty("--k", `var(--c${b.dataset.c})`));
    function draw() {
      const w = cv.clientWidth;
      if (!w) return;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const gap = w < 480 ? 5.2 : 7;
      const cols = Math.floor(w / gap);
      const rowsN = Math.ceil(N / cols);
      const h = rowsN * gap;
      cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); cv.style.height = `${h}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const off = css("--line"), on = css(color);
      const r = gap * 0.34;
      const ox = (w - cols * gap) / 2 + gap / 2;
      for (let i = 0; i < N; i++) {
        const x = ox + (i % cols) * gap, y = gap / 2 + Math.floor(i / cols) * gap;
        ctx.fillStyle = i < shown ? on : off;
        ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill();
      }
    }
    function animateTo(target) {
      cancelAnimationFrame(raf);
      const from = shown, t0 = performance.now(), dur = reduce ? 0 : 520;
      const tick = (now) => {
        const p = dur ? Math.min(1, (now - t0) / dur) : 1;
        const e = 1 - Math.pow(1 - p, 3);
        shown = Math.round(from + (target - from) * e);
        draw();
        if (p < 1) raf = requestAnimationFrame(tick);
      };
      raf = requestAnimationFrame(tick);
    }
    const crN = $("#crN"), crDef = $("#crDef"), read = $(".cohort-read");
    btns.forEach((b) => b.addEventListener("click", () => {
      btns.forEach((x) => x.setAttribute("aria-checked", String(x === b)));
      n = +b.dataset.n; color = `--c${b.dataset.c}`;
      read.style.setProperty("--k", `var(--c${b.dataset.c})`);
      crN.textContent = n.toLocaleString("en-US");
      crDef.textContent = b.dataset.def;
      animateTo(n);
    }));
    $(".cohort-list").addEventListener("keydown", (e) => {
      const i = btns.indexOf(document.activeElement);
      if (i < 0) return;
      if (e.key === "ArrowDown" || e.key === "ArrowRight") { e.preventDefault(); btns[(i + 1) % btns.length].focus(); btns[(i + 1) % btns.length].click(); }
      if (e.key === "ArrowUp" || e.key === "ArrowLeft") { e.preventDefault(); btns[(i - 1 + btns.length) % btns.length].focus(); btns[(i - 1 + btns.length) % btns.length].click(); }
    });
    read.style.setProperty("--k", "var(--c2)");
    new ResizeObserver(draw).observe(cv);
    onTheme(() => requestAnimationFrame(draw));
    draw();
  })();

  /* ---------------- negative controls ---------------- */
  (function negctrl() {
    const w = $("#nc-widget");
    if (!w) return;
    const P = {
      Random: "voxel intensities are redrawn from a uniform distribution over the region’s original range",
      Sample: "voxels are resampled with replacement from the region’s own intensity distribution, so intensity frequencies are kept",
      Shuffle: "existing voxels are reordered, so the exact histogram is kept and all spatial texture is destroyed",
    };
    const R = { Full: "across the whole image", ROI: "inside the tumour only", Background: "everywhere except the tumour" };
    const E = {
      Full: [
        "<b>No change.</b> In RADCURE every control stays within ±0.02 of the original C-index of 0.67, level with tumour volume alone.",
        "<b>Substantial drop.</b> Perturbing the whole image degraded HPV prediction.",
        "<b>Correlations diminish</b>, because the background is perturbed.",
      ],
      ROI: [
        "<b>No change.</b> Within ±0.02 of the original, level with tumour volume alone.",
        "<b>Comparatively small effect.</b> The signal does not come from inside the tumour.",
        "<b>Negligible difference</b> in correlation structure versus the original image.",
      ],
      Background: [
        "<b>No change.</b> Within ±0.02 of the original, level with tumour volume alone.",
        "<b>Substantial drop.</b> The predictive signal sits at the tumour periphery and beyond.",
        "<b>Correlations diminish.</b> The features are derived from the boundary and surroundings.",
      ],
    };
    const name = $("#ncName"), desc = $("#ncDesc"), a = $("#ncA"), c = $("#ncC"), f = $("#ncF");
    const btns = $$(".nc-grid button", w);
    function sel(b) {
      btns.forEach((x) => { x.classList.toggle("on", x === b); x.setAttribute("aria-pressed", String(x === b)); });
      const r = b.dataset.r, p = b.dataset.p;
      name.textContent = `${r} × ${p}`;
      desc.textContent = `Panel ${b.dataset.panel}: ${P[p]}, ${R[r]}.` + (r === "Full" && p === "Shuffle" ? " This configuration replicates Welch and colleagues’ 2019 experiment." : "");
      [a.innerHTML, c.innerHTML, f.innerHTML] = E[r];
    }
    btns.forEach((b) => { b.setAttribute("aria-label", `${b.dataset.r} × ${b.dataset.p}, panel ${b.dataset.panel}`); b.addEventListener("click", () => sel(b)); });
    sel($(".nc-grid button.on", w));
  })();

  /* ---------------- forest plot ---------------- */
  (function forest() {
    const w = $("#forest");
    if (!w) return;
    const rows = [
      { l: "Deep learning", s: "RADCURE held-out · n=163", hl: 1, auroc: [0.913, 0.852, 0.961], auprc: [0.603, 0.470, 0.817], base: 25 / 163 },
      { l: "Volume baseline", s: "largest GTVn size", auroc: [0.851, 0.773, 0.921], auprc: [0.498, 0.373, 0.713], base: 25 / 163 },
      { l: "Mixed baseline", s: "clinical + volume", auroc: [0.786, 0.685, 0.878], auprc: [0.474, 0.338, 0.686], base: 25 / 163 },
      { l: "Clinical baseline", s: "T, N, HPV, age, sex, smoking", auroc: [0.681, 0.575, 0.782], auprc: [0.322, 0.214, 0.495], base: 25 / 163 },
      { l: "Deep learning", s: "Maastro external · n=175", hl: 1, sep: 1, auroc: [0.671, 0.579, 0.763], auprc: [0.602, 0.498, 0.719], base: 60 / 175 },
      { l: "CT labels", s: "n=21 · 8 iENE+", auroc: [0.769, 0.538, 0.952], auprc: [0.735, 0.523, 0.934], base: 8 / 21 },
      { l: "PET-CT labels", s: "n=79 · 28 iENE+", auroc: [0.571, 0.422, 0.717], auprc: [0.587, 0.454, 0.732], base: 28 / 79 },
      { l: "MRI labels", s: "n=75 · 24 iENE+", auroc: [0.749, 0.627, 0.864], auprc: [0.598, 0.461, 0.794], base: 24 / 75 },
    ];
    const fp = $("#fp"), axis = $("#fpAxis");
    fp.innerHTML = rows.map((r) => `<div class="fp-row${r.hl ? " hl" : ""}${r.sep ? " sep" : ""}"><div class="fp-lab">${r.l}<small>${r.s}</small></div><div class="fp-track"><span class="fp-base"></span><span class="fp-ci"></span><span class="fp-pt"></span></div><div class="fp-val"></div></div>`).join("");
    const els = $$(".fp-row", fp);
    function render(m) {
      const [lo, hi, ticks] = m === "auroc" ? [0.4, 1, [0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1]] : [0, 1, [0, 0.2, 0.4, 0.6, 0.8, 1]];
      const X = (v) => `${((v - lo) / (hi - lo)) * 100}%`;
      rows.forEach((r, i) => {
        const [v, a, b] = r[m];
        const e = els[i];
        $(".fp-ci", e).style.left = X(a);
        $(".fp-ci", e).style.width = `calc(${X(b)} - ${X(a)})`;
        $(".fp-pt", e).style.left = X(v);
        $(".fp-base", e).style.left = X(m === "auroc" ? 0.5 : r.base);
        $(".fp-val", e).textContent = `${v.toFixed(3)} [${a.toFixed(3)}–${b.toFixed(3)}]`;
        e.setAttribute("aria-label", `${r.l}, ${r.s}: ${m.toUpperCase()} ${v.toFixed(3)}, 95% CI ${a.toFixed(3)} to ${b.toFixed(3)}`);
      });
      axis.innerHTML = ticks.map((t) => `<span style="left:${X(t)}">${t.toFixed(1)}</span>`).join("");
    }
    const seg = $$(".seg button", w);
    seg.forEach((b) => b.addEventListener("click", () => { seg.forEach((x) => x.setAttribute("aria-checked", String(x === b))); render(b.dataset.m); }));
    render("auroc");
  })();

  /* ---------------- threshold explorer ---------------- */
  (function threshold() {
    const w = $("#thr");
    if (!w) return;
    const D = {
      radcure: { n: 109, pos: 15, t25: [12, 18], t50: [9, 8] },
      maastro: { n: 101, pos: 37, t25: [28, 39], t50: [21, 19] },
    };
    const cols = $$(".thr-col", w);
    cols.forEach((c) => {
      const d = D[c.dataset.cohort];
      $(".dots", c).innerHTML = Array.from({ length: d.n }, (_, i) => `<i class="${i < d.pos ? "pos" : ""}"></i>`).join("");
    });
    const pct = (a, b) => `${((a / b) * 100).toFixed(1)}%`;
    function render(t) {
      cols.forEach((c) => {
        const d = D[c.dataset.cohort];
        const dots = $$(".dots i", c);
        let fpos = 0, fneg = 0;
        if (t !== "rad") { [fpos, fneg] = d[t]; }
        dots.forEach((el, i) => {
          const flagged = t === "rad" ? false : i < d.pos ? i < fpos : i - d.pos < fneg;
          el.classList.toggle("flag", flagged);
        });
        const read = $(".thr-read", c);
        if (t === "rad") {
          read.innerHTML = `The radiologist called <b>${d.pos} of ${d.n}</b> HPV-positive patients iENE-positive (<b>${pct(d.pos, d.n)}</b>).`;
        } else {
          const tot = fpos + fneg;
          read.innerHTML = `The model flags <b>${tot}</b> patients. <b>${fpos}</b> of them (<b>${pct(fpos, tot)}</b>) were iENE-positive on the radiologist’s read, covering <b>${fpos} of ${d.pos}</b> radiologist-positive patients.`;
        }
      });
    }
    const seg = $$(".seg button", w);
    seg.forEach((b) => b.addEventListener("click", () => { seg.forEach((x) => x.setAttribute("aria-checked", String(x === b))); render(b.dataset.t); }));
    render("t25");
  })();

  /* ---------------- Dosarex stepper ---------------- */
  (function dosarex() {
    const w = $("#dx");
    if (!w) return;
    const S = [
      ["Two independent inputs", "Each patient contributes a radiotherapy planning CT with its RTSTRUCT and RTDOSE, and a routine panoramic radiograph (panorex). Med-ImageTools handles the DICOM processing.", "fig-5-1"],
      ["Curved planar reformation", "The medial curve of the mandible mask is computed and a straightening transform is applied to the CT and dose volumes. A depthwise maximum-intensity projection then gives a synthetic panorex and its matching dose projection.", "fig-5-1"],
      ["Tooth segmentation in both images", "SemiT-SAM, fine-tuned on STS24-2Dxray, segments each tooth on the panorex. An nnU-Net trained on 150 annotated cases segments teeth on the projected CT, with a boundary class that separates touching teeth.", "fig-5-2"],
      ["Matching teeth across modalities", "The centroid of every segmented tooth becomes a landmark. After centering and scaling both point sets, the Hungarian algorithm pairs each CT tooth with its panorex counterpart.", "fig-5-4"],
      ["Landmark-based registration", "A similarity transform (rotation, uniform scaling, translation) is fitted to the matched pairs by least-median-of-squares, so a few wrong matches do not derail the alignment.", "fig-5-5"],
      ["Dose into panoramic space", "The planning dose is carried through the same reformation and transform, expressing the 3D dose distribution in panorex pixel coordinates.", "fig-5-6"],
      ["A dose on every tooth", "Mean dose is computed inside a dilated mask of each tooth and drawn onto the panorex the dentist already reads, ready to compare against the 70 Gy maxilla and 60 Gy mandible extraction thresholds.", "fig-5-7"],
    ];
    const tabs = $$(".dx-track button", w), h = $("#dxH"), p = $("#dxP"), fb = $("#dxFig");
    let fig = "fig-5-1";
    function sel(i) {
      tabs.forEach((t, k) => t.setAttribute("aria-selected", String(k === i)));
      [h.textContent, p.textContent, fig] = S[i];
      fb.textContent = `Open Figure ${fig.slice(4).replace("-", ".")}`;
    }
    tabs.forEach((t, i) => t.addEventListener("click", () => sel(i)));
    fb.addEventListener("click", () => window.openFigure(fig));
    sel(0);
  })();
})();
