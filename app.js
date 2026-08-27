/* sump.stream broadcast engine.
   No server: the "live" schedule is a seeded shuffle per UTC day, and your
   position in it is just the wall clock. Every viewer sees the same sump. */

(() => {
  "use strict";

  const DAY = 86400;
  const tickerEl = document.getElementById("nowplaying");

  if (!window.SUMP || !window.SUMP.videos || window.SUMP.videos.length === 0) {
    tickerEl.textContent = "no sumps loaded — run scripts/refresh_playlist.py first";
    return;
  }

  // youtube embeds require a referer header; file:// sends none (error 153)
  if (location.protocol === "file:") {
    tickerEl.textContent = "youtube refuses to sump over file:// — serve the folder instead";
    const btn = document.getElementById("tunein");
    btn.innerHTML = "no sump over file:// (´•ᴥ•｀)<br><small>run: python3 -m http.server 8000<br>then visit localhost:8000</small>";
    btn.style.cursor = "default";
    return;
  }

  const videos = window.SUMP.videos;
  document.getElementById("count").textContent = videos.length.toLocaleString("en-US");
  document.getElementById("refreshed").textContent = window.SUMP.generated;

  /* ---- deterministic daily schedule ---- */

  function mulberry32(seed) {
    let a = seed >>> 0;
    return () => {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  let cachedDay = -1;
  let order = [], cum = [], total = 0;

  function orderFor(day) {
    if (day === cachedDay) return;
    // Knuth-multiplied so consecutive days don't get correlated shuffles
    const rand = mulberry32(Math.imul(day, 2654435761));
    order = videos.slice();
    for (let i = order.length - 1; i > 0; i--) {
      const j = Math.floor(rand() * (i + 1));
      [order[i], order[j]] = [order[j], order[i]];
    }
    cum = []; total = 0;
    for (const v of order) { cum.push(total); total += v.duration; }
    cachedDay = day;
  }

  function scheduleNow() {
    const now = Date.now() / 1000;
    orderFor(Math.floor(now / DAY));
    const t = (now % DAY) % total;
    let i = 0;
    while (i + 1 < order.length && cum[i + 1] <= t) i++;
    return { index: i, offset: Math.floor(t - cum[i]) };
  }

  /* ---- player ---- */

  const badIds = new Set(); // embed-blocked or broken, skipped for this viewer
  let player = null;
  let current = -1;
  let hasPlayed = false;
  let lastPlayingAt = Date.now();

  const staticEl = document.getElementById("static");
  const tuneinEl = document.getElementById("tunein");
  const muteBtn = document.getElementById("mute");

  function setNowPlaying(title) {
    tickerEl.textContent = "now sumping: " + title;
    // restart the crawl so long titles start from the edge
    tickerEl.style.animation = "none";
    void tickerEl.offsetWidth;
    tickerEl.style.animation = "";
  }

  function playAt(index, offset) {
    let i = ((index % order.length) + order.length) % order.length;
    let hops = 0;
    while (badIds.has(order[i].id) && hops < order.length) {
      i = (i + 1) % order.length;
      offset = 0;
      hops++;
    }
    if (hops >= order.length) {
      tickerEl.textContent = "every single sump failed to load. incredible. refresh?";
      return;
    }
    current = i;
    player.loadVideoById({ videoId: order[i].id, startSeconds: offset });
    setNowPlaying(order[i].title);
  }

  function resync() {
    const s = scheduleNow();
    playAt(s.index, s.offset);
  }

  // youtube's embed sometimes boots with a stale viewport measurement and
  // leaves the video small in a white corner; a 1px resize forces a re-measure
  function kickLayout() {
    const f = player && player.getIframe && player.getIframe();
    if (!f) return;
    f.style.height = "calc(100% + 1px)";
    requestAnimationFrame(() => { f.style.height = ""; });
  }

  function onStateChange(e) {
    if (e.data === YT.PlayerState.PLAYING) {
      hasPlayed = true;
      lastPlayingAt = Date.now();
      kickLayout();
      applyCaptions(); // each new video reloads the caption module; reapply choice
    } else if (e.data === YT.PlayerState.ENDED) {
      const s = scheduleNow();
      // if the clock still points at what just ended we're running late; move on
      if (s.index === current) playAt(current + 1, 0);
      else playAt(s.index, s.offset);
    }
  }

  function onError() {
    if (current >= 0) badIds.add(order[current].id);
    playAt(current + 1, 0);
  }

  function setMuted(muted) {
    if (!player) return;
    if (muted) player.mute(); else player.unMute();
    muteBtn.textContent = muted ? "\u{1F507}" : "\u{1F50A}";
  }

  /* ---- captions: off by default ---- */

  const ccBtn = document.getElementById("cc");
  let captionsOn = false;

  function applyCaptions() {
    if (!player) return;
    if (captionsOn) {
      player.loadModule("captions");
    } else {
      // both module names: "captions" is the html5 player, "cc" the legacy one
      player.unloadModule("captions");
      player.unloadModule("cc");
    }
  }

  ccBtn.addEventListener("click", () => {
    captionsOn = !captionsOn;
    ccBtn.classList.toggle("on", captionsOn);
    ccBtn.setAttribute("aria-pressed", String(captionsOn));
    applyCaptions();
  });

  window.onYouTubeIframeAPIReady = () => {
    const s = scheduleNow();
    current = s.index;
    player = new YT.Player("player", {
      width: "100%",
      height: "100%",
      videoId: order[s.index].id,
      playerVars: {
        autoplay: 1, mute: 1, start: s.offset,
        controls: 0, disablekb: 1, fs: 0, rel: 0,
        iv_load_policy: 3, playsinline: 1,
      },
      events: {
        onReady: () => {
          player.mute();
          player.playVideo();
          kickLayout();
          setNowPlaying(order[current].title);
        },
        onStateChange,
        onError,
      },
    });
  };

  tuneinEl.addEventListener("click", () => {
    tuneinEl.classList.add("hidden");
    staticEl.classList.add("gone");
    setMuted(false);
    if (player) player.playVideo(); // the click is the autoplay-unblocking gesture
  });

  document.getElementById("shield").addEventListener("click", () => {
    if (player) setMuted(player.isMuted() === false);
  });
  muteBtn.addEventListener("click", () => {
    if (player) setMuted(player.isMuted() === false);
  });
  document.getElementById("live").addEventListener("click", resync);

  // a sump that never starts would freeze the broadcast forever; skip it.
  // gated on hasPlayed so blocked-autoplay browsers don't silently churn.
  setInterval(() => {
    if (!hasPlayed || !player || typeof player.getPlayerState !== "function") return;
    const st = player.getPlayerState();
    if (st === YT.PlayerState.PLAYING) { lastPlayingAt = Date.now(); return; }
    if (Date.now() - lastPlayingAt > 45000) {
      lastPlayingAt = Date.now();
      onError();
    }
  }, 5000);

  const tag = document.createElement("script");
  tag.src = "https://www.youtube.com/iframe_api";
  document.head.appendChild(tag);
})();
