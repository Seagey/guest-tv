/* guest-tv, the TV screen. Works with the TV's own remote: arrows move, OK opens, Back closes.
   Plain ES2019 (no ?. or ??) because some TV browsers are old. */
(function () {
  "use strict";
  window.onerror = function (msg, src, line, col) {
    try { fetch("/api/log?home=x", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ msg: String(msg), src: src, line: line, col: col, ua: navigator.userAgent }) }); } catch (e) {}
  };
  window.addEventListener("unhandledrejection", function (e) { window.onerror("promise: " + (e.reason && (e.reason.stack || e.reason.message) || e.reason), "", 0, 0); });
  var $ = function (id) { return document.getElementById(id); };
  // Older TV browsers (Fire OS 6 sticks can carry a Chrome 55 era WebView) have no CSS grid and no
  // gap between flex items. html.old tells tv.css to space things with margins instead.
  var OLD = (function () {
    var d = document.createElement("div");
    d.style.display = "flex"; d.style.flexDirection = "column"; d.style.rowGap = "1px";
    d.appendChild(document.createElement("div")); d.appendChild(document.createElement("div"));
    document.documentElement.appendChild(d);
    var gap = d.scrollHeight === 1;
    d.parentNode.removeChild(d);
    return !gap || !(window.CSS && CSS.supports && CSS.supports("display", "grid"));
  })();
  if (OLD) document.documentElement.className += " old";
  var QS = {};
  location.search.replace(/^\?/, "").split("&").forEach(function (kv) {
    if (kv) { var p = kv.split("="); QS[decodeURIComponent(p[0])] = decodeURIComponent(p[1] || ""); }
  });
  var HOME = QS.home || QS.tv || "";   // the couch-tv TV app adds ?tv=<id>
  var S = null, WX = null, AC = null, HUB = null, CARDS = [], APPS = [], PILLS = [];
  var area = "cards", idx = 0, appIdx = 0;
  var sheet = null;   // {id, nav: [...], navIdx, zoneIdx, inMain}
  var TVOS = window.TVOS || null;   // the couch-tv TV app gives the page apps() and launch()
  var BRAND = QS.brand || "";   // "samsung" or "lg": the guest-tv app there; apps open through the computer
  var BRAND_APPS = null;

  function api(path, body) {
    var url = "/api/" + path + (path.indexOf("?") >= 0 ? "&" : "?") + "home=" + encodeURIComponent(HOME) +
      (QS.phase ? "&phase=" + encodeURIComponent(QS.phase) : "");
    var o = body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {};
    return fetch(url, o).then(function (r) { return r.json(); });
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  // ---------------------------------------------------------------- icons
  var I = {
    stay: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/><path d="M10 20v-5h4v5"/></svg>',
    wifi: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M2.5 8.5a14 14 0 0 1 19 0"/><path d="M5.5 12a9.5 9.5 0 0 1 13 0"/><path d="M8.6 15.4a5 5 0 0 1 6.8 0"/><circle cx="12" cy="19" r="1.2" fill="currentColor" stroke="none"/></svg>',
    climate: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M12 3v18M4.2 7.5l15.6 9M4.2 16.5l15.6-9"/><path d="M9.5 4.5L12 7l2.5-2.5M9.5 19.5L12 17l2.5 2.5"/></svg>',
    guide: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v15H6.5A2.5 2.5 0 0 0 4 20.5z"/><path d="M4 20.5A2.5 2.5 0 0 0 6.5 23H20v-5"/><path d="M9 8h7M9 11.5h5"/></svg>',
    local: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"><path d="M12 21s-6.5-6.2-6.5-11.2a6.5 6.5 0 0 1 13 0C18.5 14.8 12 21 12 21z"/><circle cx="12" cy="9.8" r="2.3"/></svg>',
    checkout: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M14 4h5v16h-5"/><path d="M10 8l-4 4 4 4"/><path d="M6 12h10"/></svg>',
    weather: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><circle cx="9" cy="9" r="3.5"/><path d="M9 2.5v1.5M2.5 9H4M4.4 4.4l1 1M13.6 4.4l-1 1"/><path d="M8 20h9a3.5 3.5 0 0 0 0-7 5 5 0 0 0-9.4 1.6A2.7 2.7 0 0 0 8 20z"/></svg>',
    hub: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7.5" height="7.5" rx="2"/><rect x="13.5" y="3" width="7.5" height="7.5" rx="2"/><rect x="3" y="13.5" width="7.5" height="7.5" rx="2"/><circle cx="17.25" cy="17.25" r="3.75"/></svg>',
    pool: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M2.5 16c1.6 0 1.6-1.2 3.2-1.2s1.6 1.2 3.2 1.2 1.6-1.2 3.1-1.2 1.6 1.2 3.2 1.2 1.6-1.2 3.2-1.2 1.6 1.2 3.1 1.2"/><path d="M2.5 20c1.6 0 1.6-1.2 3.2-1.2s1.6 1.2 3.2 1.2 1.6-1.2 3.1-1.2 1.6 1.2 3.2 1.2 1.6-1.2 3.2-1.2 1.6 1.2 3.1 1.2"/><path d="M8 13V5.5a2 2 0 0 1 4 0M16 13V5.5a2 2 0 0 0-4 0M8 8.5h8"/></svg>',
    music: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18V5l11-2v13"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="17.5" cy="16" r="2.5"/></svg>',
    light: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18h6M10 21h4"/><path d="M12 3a6 6 0 0 0-3.6 10.8c.6.5 1 1.2 1 2V16h5.2v-.2c0-.8.4-1.5 1-2A6 6 0 0 0 12 3z"/></svg>',
    notes: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"><rect x="4" y="3" width="16" height="18" rx="2.5"/><path d="M8 8h8M8 12h8M8 16h5"/></svg>'
  };
  function wx(code, day) {
    var c = +code, s = 'fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"';
    var sun = '<circle cx="12" cy="12" r="4.2"/><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4"/>';
    var moon = '<path d="M19 14.5A7.5 7.5 0 0 1 9.5 5a7.5 7.5 0 1 0 9.5 9.5z"/>';
    var cloud = '<path d="M7 19h10a4 4 0 0 0 .6-8A6 6 0 0 0 6.2 12.6 3.3 3.3 0 0 0 7 19z"/>';
    var body;
    if (c <= 1) body = day === 0 ? moon : sun;
    else if (c === 2) body = '<g transform="translate(-3 -3) scale(.8)">' + (day === 0 ? moon : sun) + '</g><path d="M9 20h8.5a3.3 3.3 0 0 0 .4-6.6 5 5 0 0 0-9.6 1.3A2.7 2.7 0 0 0 9 20z" fill="rgba(20,20,26,.35)"/>';
    else if (c === 3) body = cloud;
    else if (c === 45 || c === 48) body = '<path d="M4 9h16M3 13h18M5 17h14"/>';
    else if (c >= 95) body = cloud.replace("19h", "16h") + '<path d="M12 16l-2 4h3l-2 3"/>';
    else if ((c >= 71 && c <= 77) || c === 85 || c === 86) body = '<path d="M7 16h10a4 4 0 0 0 .6-8A6 6 0 0 0 6.2 9.6 3.3 3.3 0 0 0 7 16z"/><path d="M9 20h.01M12 21h.01M15 20h.01"/>';
    else body = '<path d="M7 15h10a4 4 0 0 0 .6-8A6 6 0 0 0 6.2 8.6 3.3 3.3 0 0 0 7 15z"/><path d="M9 18l-1 2.5M13 18l-1 2.5M17 18l-1 2.5"/>';
    return '<svg viewBox="0 0 24 24" ' + s + ">" + body + "</svg>";
  }

  // ---------------------------------------------------------------- dates and times
  var DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
  var MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
  function d8(iso) { var p = String(iso).slice(0, 10).split("-"); return new Date(+p[0], +p[1] - 1, +p[2]); }
  function day3(d) { return DAYS[d.getDay()].slice(0, 3); }
  function dayShort(iso) { var d = d8(iso); return day3(d) + " " + d.getDate() + " " + MONTHS[d.getMonth()].slice(0, 3); }
  function t12(hhmm) {
    if (!hhmm) return "";
    var p = String(hhmm).split(":"), h = +p[0], m = p[1] || "00";
    return (h % 12 || 12) + (m === "00" ? "" : ":" + m) + (h < 12 ? "am" : "pm");
  }
  function isoToday() { var d = new Date(); return d.getFullYear() + "-" + ("0" + (d.getMonth() + 1)).slice(-2) + "-" + ("0" + d.getDate()).slice(-2); }
  function greeting() { var h = new Date().getHours(); return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening"; }

  // ---------------------------------------------------------------- scene and clock
  var glassShown = "";
  function buildScene() {
    var sc = $("scene"), hero = (S.photos && S.photos.hero) || "";
    var old = sc.querySelectorAll("img");
    for (var i = 0; i < old.length; i++) sc.removeChild(old[i]);
    var bg = new Image(); bg.className = "sbg"; bg.alt = ""; bg.src = "homes/" + hero + ".jpg";
    sc.insertBefore(bg, $("gclock"));
    var fg = new Image(); fg.className = "fg"; fg.alt = "";
    fg.onerror = function () { if (fg.parentNode) fg.parentNode.removeChild(fg); };
    fg.src = "homes/" + hero + "-fg.webp";
    if ((S.scene || {}).fg !== false) sc.insertBefore(fg, sc.querySelector(".shade"));   // fg: false when the scenery would hide the time
    var c = $("gclock"), sz = S.scene || {};
    c.style.top = (sz.clockTop || 7.5) + "rem";
    c.style.fontSize = (sz.clockSize || 25) + "rem";
    c.style.left = c.style.right = "0";
    if (sz.clockX) { c.style.left = (sz.clockX * 2) + "rem"; }   // + moves right, - moves left (centre stays centred on the shifted box)
    document.documentElement.style.setProperty("--fill", sz.fill || "brightness(1.12) saturate(1.15)");
    glassShown = "";
    clock();
  }
  function clock() {
    var d = new Date(), hm = (d.getHours() % 12 || 12) + ":" + ("0" + d.getMinutes()).slice(-2);
    document.documentElement.classList.toggle("late", d.getHours() >= 21 || d.getHours() < 5);
    if (hm !== glassShown && S) {
      glassShown = hm;
      var c = $("gclock");
      c.innerHTML = '<span class="fill">' + hm + '</span><span class="sheen">' + hm + '</span><span class="rim">' + hm + "</span>";
      var f = c.firstChild;
      f.style.backgroundImage = "url(homes/" + S.photos.hero + "-glass.jpg)";
      f.style.backgroundPosition = -(c.offsetLeft + f.offsetLeft) + "px " + -(c.offsetTop + f.offsetTop) + "px";
      dateLine();
    }
  }
  function dateLine() {
    var d = new Date(), out = DAYS[d.getDay()] + " " + d.getDate() + " " + MONTHS[d.getMonth()];
    if (WX && WX.ok) out += '<span class="wx">' + wx(WX.now.code, WX.now.day) + WX.now.temp + "° " + esc(WX.place) + "</span>";
    $("date").innerHTML = out;
  }

  // ---------------------------------------------------------------- header
  function header() {
    var st = S.stay || {}, guest = st.guest || "";
    var eyebrow = S.name, h1 = "", sub = "";
    if (S.mode === "guest") {
      eyebrow = S.host ? "Staying with " + S.host : S.name;
      h1 = guest ? greeting() + ", " + guest : "Welcome";
      sub = st.to ? "Here until " + DAYS[d8(st.to).getDay()] + ". Make yourself at home." : "Make yourself at home.";
    } else if (st.phase === "open") {
      eyebrow = S.kind || (S.brand && S.brand.name) || "";
      h1 = "Welcome to " + S.name;
      sub = "Make yourself at home." + (S.checkout_time ? " Check-out is by " + t12(S.checkout_time) + "." : "");
    } else if (st.phase === "between" || st.phase === "before") {
      eyebrow = S.kind;
      h1 = "Welcome to " + S.name;
      sub = "Your stay details show here when you arrive.";
    } else if (st.phase === "arrival") {
      h1 = "Welcome" + (guest ? ", " + guest : "");
      sub = "Check-in from " + t12(S.checkin) + " today. Settle in, everything is here.";
    } else if (st.phase === "lastday") {
      h1 = greeting() + (guest ? ", " + guest : "");
      sub = "Check-out today at " + t12(S.checkout_time) + ". Thanks for staying.";
    } else {
      h1 = (st.night === 1 ? "Welcome" : greeting()) + (guest ? ", " + guest : "");
      sub = dayShort(st.from) + " to " + dayShort(st.to) + " · Night " + st.night + " of " + st.nights;
    }
    $("eyebrow").textContent = eyebrow || "";
    var logo = $("brand"), src = S.brand && S.brand.logo;
    if (src && logo.getAttribute("src") !== src) { logo.alt = S.brand.name || ""; logo.src = src; }
    logo.style.display = src ? "" : "none";
    $("welcome").textContent = h1;
    $("sub").textContent = sub;
    document.body.classList.toggle("between", S.mode !== "guest" && !st.active);
    // Step 1 joins the Wi-Fi, step 2 opens the Guest remote (it only works on the Wi-Fi)
    $("wifi-step").style.display = S.wifi && S.wifi.ssid ? "" : "none";
    if (S.wifi && S.wifi.ssid) loadSvg($("wifi-qr"), "wifi");
    loadSvg($("phone-qr"), S.remote_url ? "remote" : "qr");
    $("phone-what").textContent = S.remote_url ? (S.wifi && S.wifi.ssid ? "2 · " : "") + "Guest remote" : "On your phone";
  }
  var svgCache = {};
  function loadSvg(el, what) {
    var key = HOME + what;
    if (svgCache[key]) { el.innerHTML = svgCache[key]; return; }
    fetch("/api/qr?home=" + encodeURIComponent(HOME) + (what === "wifi" || what === "remote" ? "&what=" + what : "")).then(function (r) {
      return r.ok ? r.text() : "";
    }).then(function (t) { svgCache[key] = t; el.innerHTML = t; });
  }

  // ---------------------------------------------------------------- cards
  function forecastDays(from, to, max) {
    if (!WX || !WX.ok) return [];
    var t = isoToday();
    return WX.days.filter(function (d) { return d.date >= t && (!from || d.date >= from.slice(0, 10)) && (!to || d.date <= to.slice(0, 10)); }).slice(0, max || 5);
  }
  function fcHtml(days, wide) {
    var t = isoToday();
    return '<div class="fc' + (wide ? " wide" : "") + '">' + days.map(function (d) {
      return '<div class="d' + (d.date === t ? " today" : "") + '"><b>' + (d.date === t ? "Today" : day3(d8(d.date))) + "</b>" + wx(d.code, 1) +
        "<span>" + d.hi + "°<i>" + d.lo + "°</i></span>" + (wide && d.rain > 20 ? "<em>" + d.rain + "% rain</em>" : "") + "</div>";
    }).join("") + "</div>";
  }
  function climateSummary() {
    if (!AC || !AC.connected) return { big: "…", small: AC && AC.connected === false ? "Not answering" : "Checking" };
    var on = AC.zones.filter(function (z) { return z.on; });
    var z0 = on[0] || AC.zones[0] || {};
    var mode = AC.mode === "heat" ? "Heating" : AC.mode === "cool" ? "Cooling" : AC.mode === "fan" ? "Fan" : "On";
    return {
      big: (z0.temp != null ? Math.round(z0.temp * 10) / 10 + "°" : "−"),
      small: on.length && AC.power === "on" ? mode + " to " + (z0.setpoint || "") + "° in " + (z0.label || z0.name) : "Off · " + (z0.label || z0.name || "")
    };
  }
  function cardDefs() {
    var st = S.stay || {}, out = [], g = S.rules.length + S.howto.length + (S.notes || []).length;
    var places = S.local.reduce(function (n, c) { return n + (c.items || []).length; }, 0);
    var cs = climateSummary();
    var stayCard = { id: "stay", w: 2.3, html: function () {
      var days = forecastDays(st.from, st.to, 5);
      var line = st.phase === "lastday" ? "Last day · Check-out " + t12(S.checkout_time) : st.phase === "arrival" ? "Arriving today · Check-in " + t12(S.checkin)
        : "Night " + st.night + " of " + st.nights + " · out " + DAYS[d8(st.to).getDay()].slice(0, 3) + " " + t12(S.checkout_time);
      return '<div class="k">' + I.stay + "Your stay</div>" + '<div class="mid one">' + esc(line) + "</div>" + fcHtml(days.length ? days : forecastDays(null, null, 4));
    } };
    var wifiCard = { id: "wifi", w: 1.7, html: function () {
      return '<div class="k">' + I.wifi + "Wi-Fi</div>" + (S.wifi && S.wifi.ssid ?
        '<div><div class="small">' + esc(S.wifi.ssid) + '</div><div class="pw">' + esc(S.wifi.password || "No password") + '</div><div class="small">OK for a code to join</div></div>'
        : '<div class="small">Ask ' + esc(S.host || "your host") + " for the Wi-Fi</div>");
    } };
    var climateCard = { id: "climate", w: S.mode === "guest" ? 1.8 : 1.4, html: function () {
      var c = climateSummary();
      return '<div class="k">' + I.climate + (S.mode === "guest" ? "Your room" : "Climate") + "</div>" +
        '<div><div class="big">' + c.big + '</div><div class="small">' + esc(c.small) + "</div></div>";
    } };
    var hasHub = HUB && (HUB.pool || (HUB.speakers || []).length);
    var hubCard = { id: "hub", w: 1.6, html: function () {
      var c = climateSummary(), p = HUB.pool, sp = (HUB.speakers || []).filter(function (x) { return x.playing; })[0] || (HUB.speakers || [])[0];
      var row = function (icon, name, val, note) {
        return '<div class="hubrow">' + icon + "<i>" + esc(name) + "</i><b>" + esc(val) + "</b><span>" + esc(note) + "</span></div>";
      };
      return '<div class="k">' + I.hub + "Smart home</div><div>" +
        row(I.climate, "Inside", c.big, AC && AC.power === "on" ? "On" : "Off") +
        (p ? row(I.pool, "Pool", p.temp != null ? p.temp + "°" : "−", p.heater ? "Heating" : "Heater off") : "") +
        (sp ? row(I.music, sp.label, sp.playing ? "Playing" : "Paused", sp.playing ? sp.title || "" : "") : "") + "</div>";
    } };
    var guideCard = { id: "guide", w: 1, html: function () {
      return '<div class="k">' + I.guide + "House guide</div><div><div class=\"mid\">" + g + ' things</div><div class="small">Rules and how things work</div></div>';
    } };
    var checkoutCard = { id: "checkout", w: 1, html: function () {
      return '<div class="k">' + I.checkout + "Check-out</div><div><div class=\"mid\">" + (st.phase === "lastday" ? "Today " : DAYS[d8(st.to).getDay()].slice(0, 3) + " ") + t12(S.checkout_time) +
        '</div><div class="small">' + ((S.checkout.steps || []).length ? (S.checkout.steps || []).length + " quick things" : "Thanks for staying") + "</div></div>";
    } };
    var weatherCard = { id: "weather", w: 1.8, html: function () {
      var fd = forecastDays(null, null, 4);
      return '<div class="k">' + I.weather + "Weather</div>" + (fd.length ? fcHtml(fd) : '<div class="small">The forecast shows here when it loads</div>');
    } };
    var eat = S.local.filter(function (c) { return /^eat/i.test(c.category); })[0] || S.local[0];
    var todo = S.local.filter(function (c) { return /things to do|do\b/i.test(c.category); })[0] || S.local[1];
    var localCard = { id: "local", w: 1.8, photo: S.photos && S.photos.area, html: function () {
      var line = function (label, c) {
        var it = c && c.items && c.items[0];
        return it ? '<div class="pick"><i>' + esc(label) + "</i>" + esc(it.name) + "</div>" : "";
      };
      return '<div class="k">' + I.local + "Around here</div><div>" + line("Eat", eat) + line("Do", todo) +
        '<div class="small">' + places + " local picks</div></div>";
    } };
    var welcomeCard = { id: "about", w: 2, html: function () {
      return '<div class="k">' + I.stay + esc(S.name) + '</div><div class="small clamp" style="font-size:1.625rem;line-height:2.25rem;color:#fff">' + esc(S.welcome) + "</div>";
    } };

    var pills = [{ id: "guide", name: S.mode === "guest" ? "How things work" : "House guide", icon: I.guide, note: g ? g + "" : "" }];
    var localPill = { id: "local", name: "Around here", icon: I.local, note: places ? places + "" : "" };
    var noAC = !S.has_climate && !hasHub;   // no aircon here: the house guide takes that tile
    if (noAC) { guideCard.w = 1.2; }
    if (S.mode === "guest") {
      out = (noAC ? [] : [climateCard]).concat(places ? [wifiCard, weatherCard, localCard] : [wifiCard, weatherCard]);
      climateCard.w = 1.45; wifiCard.w = 1.5; weatherCard.w = 1.55;
    } else if (st.phase === "open") {
      wifiCard.w = 1.5; weatherCard.w = 1.6;
      out = [welcomeCard, wifiCard, noAC ? weatherCard : climateCard].concat(places ? [localCard] : []);
      if (S.checkout_time) pills.push({ id: "checkout", name: "Check-out", icon: I.checkout, note: t12(S.checkout_time) });
    } else if (!st.active) {
      out = places ? [welcomeCard, weatherCard, localCard] : [welcomeCard, weatherCard];
    } else if (st.phase === "lastday") {
      checkoutCard.lead = true; checkoutCard.w = 1.3;
      if (hasHub) { climateCard = hubCard; }
      if (noAC) { climateCard = guideCard; }
      out = [checkoutCard, stayCard, wifiCard, climateCard];
      stayCard.w = 2; climateCard.w = hasHub ? 1.6 : 1.2;
      if (places) pills.push(localPill);
    } else {
      stayCard.w = 2; wifiCard.w = 1.45; climateCard.w = 1.2;
      if (hasHub) { climateCard = hubCard; climateCard.w = 1.75; stayCard.w = 1.9; wifiCard.w = 1.35; }
      if (noAC) { climateCard = guideCard; }
      out = places ? [stayCard, wifiCard, climateCard, localCard] : [stayCard, wifiCard, climateCard];
      pills.push({ id: "checkout", name: "Check-out", icon: I.checkout, note: DAYS[d8(st.to).getDay()].slice(0, 3) + " " + t12(S.checkout_time) });
    }
    PILLS = pills;
    return out;
  }
  function drawCards() {
    CARDS = cardDefs();
    var box = $("cards");
    box.style.gridTemplateColumns = CARDS.map(function (c) { return c.w + "fr"; }).join(" ");
    box.innerHTML = CARDS.map(function (c, i) {
      return '<div class="card glass' + (c.lead ? " lead" : "") + (c.photo ? " photo" : "") + '" data-i="' + i + '"' +
        (c.photo ? ' style="background-image:linear-gradient(180deg,rgba(0,0,0,.25),rgba(0,0,0,.62)),url(homes/' + c.photo + '.jpg)"' : "") + ">" + c.html() + "</div>";
    }).join("");
    if (OLD) for (var j = 0; j < CARDS.length; j++) box.children[j].style.flex = CARDS[j].w + " 1 0%";
    var q = box.querySelectorAll("[data-qr]");
    for (var k = 0; k < q.length; k++) loadSvg(q[k], q[k].getAttribute("data-qr"));
    if (idx >= CARDS.length) idx = 0;
    paintFocus();
  }
  function refreshCard(id) {
    for (var i = 0; i < CARDS.length; i++) {
      if (CARDS[i].id === id) {
        var el = $("cards").children[i];
        if (el) el.innerHTML = CARDS[i].html();
      }
    }
  }

  // ---------------------------------------------------------------- apps
  var PREFER = ["com.netflix.ninja", "com.google.android.youtube.tv", "com.amazon.amazonvideo.livingroom", "com.disney.disneyplus",
    "au.com.stan.and", "au.net.abc.iview", "com.sbs.ondemand.tv", "com.spotify.tv.android", "com.apple.atve.androidtv.appletv",
    "au.com.streamotion.ares", "com.cbs.ca", "au.com.seven", "au.com.nine.jumpin", "au.com.tenplay"];
  function drawApps() {
    var list = [];
    if (BRAND) {
      list = (BRAND_APPS || []).map(function (a) { return { name: a.name, app: a.id }; });
    } else if (TVOS && TVOS.apps) {
      try {
        var all = JSON.parse(TVOS.apps());
        list = all.filter(function (a) { return PREFER.indexOf(a.package) >= 0; })
          .sort(function (a, b) { return PREFER.indexOf(a.package) - PREFER.indexOf(b.package); })
          .slice(0, 6).map(function (a) { return { name: a.label, pkg: a.package, banner: "http://tvos.invalid/banner/" + a.package }; });
      } catch (e) { list = []; }
    } else {
      list = ["Netflix", "YouTube", "Prime Video", "Disney+", "Spotify"].map(function (n) { return { name: n }; });
    }
    APPS = PILLS.map(function (p) { return { name: p.name, sheet: p.id, icon: p.icon, note: p.note }; }).concat(list);
    var box = $("apps");
    box.classList.toggle("none", !APPS.length);
    box.innerHTML = APPS.map(function (a, i) {
      if (a.sheet) return '<div class="app pill glass" data-a="' + i + '">' + a.icon + esc(a.name) + (a.note ? "<i>" + esc(a.note) + "</i>" : "") + "</div>" + (i === PILLS.length - 1 && APPS.length > PILLS.length ? '<span class="sep"></span>' : "");
      return a.banner ? '<div class="app banner glass" data-a="' + i + '"><img src="' + esc(a.banner) + '" alt="' + esc(a.name) + '"></div>'
        : '<div class="app glass" data-a="' + i + '">' + esc(a.name) + "</div>";
    }).join("");
    paintFocus();
  }

  // ---------------------------------------------------------------- focus on the home
  function paintFocus() {
    var cs = $("cards").children, as = $("apps").querySelectorAll("[data-a]");
    for (var i = 0; i < cs.length; i++) cs[i].classList.toggle("focus", !sheet && area === "cards" && i === idx);
    for (var j = 0; j < as.length; j++) as[j].classList.toggle("focus", !sheet && area === "apps" && j === appIdx);
  }
  function homeKey(k) {
    if (k === "left" || k === "right") {
      var d = k === "left" ? -1 : 1;
      if (area === "cards") idx = Math.max(0, Math.min(CARDS.length - 1, idx + d));
      else appIdx = Math.max(0, Math.min(APPS.length - 1, appIdx + d));
    } else if (k === "down" && area === "cards" && APPS.length) {
      area = "apps"; appIdx = Math.min(APPS.length - 1, Math.round(idx * APPS.length / Math.max(1, CARDS.length)));
    } else if (k === "up" && area === "apps") {
      area = "cards";
    } else if (k === "ok") {
      if (area === "cards") openSheet(CARDS[idx].id);
      else launch(APPS[appIdx]);
    }
    paintFocus();
  }
  function launch(a) {
    if (!a) return;
    if (a.sheet) { openSheet(a.sheet); return; }
    if (TVOS && TVOS.launch && a.pkg) { TVOS.launch(a.pkg); return; }
    if (BRAND && a.app) {
      toast("Opening " + a.name);
      api("tv/app", { app: a.app }).then(function (r) { if (!r.ok) toast(r.error || a.name + " did not open"); },
        function () { toast(a.name + " did not open"); });
      return;
    }
    toast(a.name + " opens here on the TV");
  }
  var toastT = 0;
  function toast(msg) {
    var t = $("toast");
    t.textContent = msg; t.classList.add("on");
    clearTimeout(toastT); toastT = setTimeout(function () { t.classList.remove("on"); }, 2600);
  }

  // ---------------------------------------------------------------- sheets
  function navList(id) {
    var st = S.stay || {};
    if (id === "guide") {
      var out = [];
      if ((S.notes || []).length) { out.push({ group: "From " + (S.host || "your host") }); S.notes.forEach(function (x) { out.push({ t: x.title, body: x.body }); }); }
      if (S.rules.length) { out.push({ group: "House rules" }); S.rules.forEach(function (x) { out.push({ t: x.title, body: x.body }); }); }
      var grp = null;
      S.howto.forEach(function (x) {
        var g2 = x.group || "How things work";
        if (g2 !== grp) { grp = g2; out.push({ group: g2 }); }
        out.push({ t: x.title, body: x.body });
      });
      return out;
    }
    if (id === "hub") {
      var h = [];
      if (AC && AC.connected && AC.zones.length) h.push({ t: "Air conditioning", k: "ac" });
      if (HUB && HUB.pool) h.push({ t: "Pool", k: "pool" });
      if (HUB && (HUB.speakers || []).length) h.push({ t: "Speakers", k: "spk" });
      if (HUB && hubLights().length) h.push({ t: "Lights", k: "lights" });
      return h;
    }
    if (id === "local") {
      var l = S.local.map(function (c) { return { t: c.category, items: c.items || [] }; });
      if (S.emergency.length) l.push({ t: "Emergency", emergency: true });
      return l;
    }
    if (id === "stay" || id === "about") {
      var s = [{ t: "Welcome", k: "welcome" }];
      if (st.active && (S.access || []).length) s.push({ t: "Getting in", k: "access" });
      if (st.from) s.push({ t: "Check-in and out", k: "times" });
      s.push({ t: "Weather", k: "weather" });
      if (S.emergency.length) s.push({ t: "If you need help", k: "help" });
      return s;
    }
    return [];
  }
  var TITLES = { hub: "Smart home", stay: "Your stay", about: "Welcome", wifi: "Wi-Fi", climate: "Climate", guide: "House guide", local: "Around here", checkout: "Check-out", weather: "Weather" };
  function openSheet(id) {
    if (id === "weather") id = S.mode === "guest" ? "weather" : "stay";
    var nav = navList(id);
    var first = 0;
    while (nav[first] && nav[first].group) first++;
    sheet = { id: id, nav: nav, navIdx: first, sel: first, zoneIdx: 0 };
    if (id === "climate") refreshAircon();
    if (id === "hub") { sheet.inMain = false; sheet.item = 0; refreshHub(); }
    drawSheet();
    $("sheet").classList.add("on");
    document.body.classList.add("sheeted");
    paintFocus();
  }
  function closeSheet() {
    sheet = null;
    $("sheet").classList.remove("on");
    document.body.classList.remove("sheeted");
    paintFocus();
  }
  function drawSheet() {
    var sh = sheet, navHtml = "<h2>" + esc(S.mode === "guest" && sh.id === "climate" ? "Your room" : S.mode === "guest" && sh.id === "guide" ? "How things work" : TITLES[sh.id] || "") + "</h2>";
    navHtml += sh.nav.map(function (n, i) {
      if (n.group) return '<div class="group">' + esc(n.group) + "</div>";
      return '<div class="item' + (i === sh.sel ? " sel" : "") + (i === sh.navIdx && sh.id !== "climate" && !sh.inMain ? " focus" : "") + '" data-n="' + i + '">' + esc(n.t) + "</div>";
    }).join("");
    if (sh.id === "climate") navHtml += '<p class="climate-note">' + esc(climateNote()) + "</p>";
    if (sh.id === "wifi" || sh.id === "checkout") navHtml += '<p class="climate-note">' + (sh.id === "wifi" ? "Point your phone's camera at the code to join." : "Thanks for looking after the place.") + "</p>";
    $("sheet-nav").innerHTML = navHtml;
    var navEl = $("sheet-nav"), fo = navEl.querySelector(".item.focus") || navEl.querySelector(".item.sel");
    navEl.scrollTop = fo ? Math.max(0, fo.offsetTop - navEl.offsetTop - navEl.clientHeight / 2 + fo.offsetHeight / 2) : 0;
    $("sheet-main").innerHTML = sheetMain();
    $("sheet-main").classList.toggle("mid", sh.id === "climate" || sh.id === "wifi" || sh.id === "checkout");
    $("sheet").classList.toggle("wide-nav", sh.id === "guide");   // questions from the Concierge need the room
    var q = $("sheet-main").querySelectorAll("[data-qr]");
    for (var k = 0; k < q.length; k++) loadSvg(q[k], q[k].getAttribute("data-qr"));
    if (sh.id === "hub") { $("sheet-hint").innerHTML = hubHint(); return; }
    $("sheet-hint").innerHTML = sh.id === "climate"
      ? "<b>Up</b> and <b>down</b> change the temperature · <b>OK</b> turns a room on or off · <b>Back</b> to close"
      : sh.nav.length ? "<b>Up</b> and <b>down</b> to move · <b>Back</b> to close" : "<b>Back</b> to close";
  }
  function climateNote() {
    if (!AC || !AC.connected) return "Checking the air conditioning.";
    var mode = AC.mode === "heat" ? "heating" : AC.mode === "cool" ? "cooling" : AC.mode;
    var n = "The house is set to " + mode + ". " + (AC.power === "on" ? "The system is running." : "The system is off; switching a room on starts it.");
    if (AC.simulated) n += " This is a demo home, so nothing real is switched.";
    else if (AC.preview) n += " Preview: changes show here but are not sent yet.";
    return n;
  }
  function sheetMain() {
    var sh = sheet, st = S.stay || {}, n = sh.nav[sh.sel] || {};
    var photo = function (key, label) {
      var p = S.photos && S.photos[key];
      return p ? '<div class="photo-panel" style="background-image:url(homes/' + p + '.jpg)"><span>' + esc(label || "") + "</span></div>" : "";
    };
    if (sh.id === "wifi") {
      if (!S.wifi || !S.wifi.ssid) return '<div class="panel glass"><p class="lede">Ask ' + esc(S.host || "your host") + " for the Wi-Fi details.</p></div>";
      return '<div class="panel glass wifi-big"><div class="qr" data-qr="wifi"></div><div><div class="name">Network</div><div class="val">' + esc(S.wifi.ssid) +
        '</div><div class="name">Password</div><div class="val">' + esc(S.wifi.password || "None needed") + "</div></div></div>" +
        '<div class="panel glass" style="display:flex;gap:2rem;align-items:center"><div class="qr" data-qr="qr" style="width:9rem;height:9rem;border-radius:1rem;overflow:hidden;background:#fff;flex:none"></div>' +
        '<div><h3>On your phone too</h3><p>Once you are on the Wi-Fi, this code opens the house guide and local tips on your phone. Nothing to install.</p></div></div>';
    }
    if (sh.id === "climate") return zonesHtml();
    if (sh.id === "hub") return hubMain();
    if (sh.id === "checkout") {
      var steps = (S.checkout.steps || []).map(function (x) { return "<li>" + esc(x) + "</li>"; }).join("");
      var day = st.phase === "lastday" ? "Today" : st.to ? DAYS[d8(st.to).getDay()] : "";
      return '<div class="panel glass">' + (day ? '<p class="meta">' + day + "</p>" : "") + '<h3>Check-out by ' + t12(S.checkout_time) + "</h3>" + (steps ? "<ol>" + steps + "</ol>" : "") + "</div>" +
        '<div class="panel glass"><p class="lede">Safe travels' + (st.guest ? ", " + esc(st.guest) : "") + ". We hope you come back." + "</p>" + (S.host ? '<p class="meta">' + esc(S.host) + "</p>" : "") + "</div>";
    }
    if (sh.id === "weather") {
      return '<div class="panel glass"><h3>' + esc(WX && WX.place || "") + '</h3><p class="meta">The next few days</p>' + fcHtml(forecastDays(null, null, 7), true) + "</div>";
    }
    if (sh.id === "guide") {
      return photo("inside", "") + '<div class="panel glass"><h3>' + esc(n.t) + '</h3><p class="lede" style="margin-top:1rem">' + esc(n.body) + "</p></div>";
    }
    if (sh.id === "local") {
      if (n.emergency) {
        return '<div class="panel glass"><h3>Emergency</h3><div class="places">' + S.emergency.map(function (e) {
          return '<div class="pl"><b>' + esc(e.phone || "") + "</b><p>" + esc(e.name) + "</p></div>";
        }).join("") + "</div></div>";
      }
      return (sh.sel === 0 ? photo("area", "Around " + S.name) : "") + '<div class="panel glass places">' + n.items.map(function (p) {
        return '<div class="pl"><b>' + esc(p.name) + "</b><p>" + esc(p.note || "") + (p.distance ? " <em>" + esc(p.distance) + "</em>" : "") + (p.phone ? " <em>" + esc(p.phone) + "</em>" : "") + "</p></div>";
      }).join("") + "</div>";
    }
    if (sh.id === "stay" || sh.id === "about") {
      if (n.k === "welcome") return photo("inside", "") + '<div class="panel glass"><p class="lede">' + esc(S.welcome) + "</p>" + (S.host ? '<p class="meta">' + esc(S.host) + ", your host</p>" : "") + "</div>";
      if (n.k === "access") return '<div class="panel glass">' + S.access.map(function (a) { return '<div class="kv"><span>' + esc(a.label) + "</span><b>" + esc(a.code) + "</b></div>"; }).join("") +
        '</div><div class="panel glass"><p>Codes are shown only during your stay.</p></div>';
      if (n.k === "times") return '<div class="panel glass"><div class="kv"><span>Check-in</span><b>' + dayShort(st.from) + ", " + t12(S.checkin) + '</b></div><div class="kv"><span>Check-out</span><b>' +
        dayShort(st.to) + ", " + t12(S.checkout_time) + "</b></div>" + (st.nights ? '<div class="kv"><span>Nights</span><b>' + st.nights + "</b></div>" : "") +
        (st.guests ? '<div class="kv"><span>Guests</span><b>' + st.guests + "</b></div>" : "") + "</div>";
      if (n.k === "weather") return '<div class="panel glass"><h3>Your stay in ' + esc(WX && WX.place || "") + "</h3>" + fcHtml(forecastDays(st.from || null, st.to || null, 7).length ? forecastDays(st.from || null, st.to || null, 7) : forecastDays(null, null, 5), true) + "</div>";
      if (n.k === "help") return '<div class="panel glass places">' + S.emergency.map(function (e) {
        return '<div class="pl"><b>' + esc(e.phone || "") + "</b><p>" + esc(e.name) + "</p></div>";
      }).join("") + "</div>" + (S.host ? '<div class="panel glass"><p>For anything about the house, message ' + esc(S.host) + " through the app you booked with.</p></div>" : "");
    }
    return "";
  }
  // ---------------------------------------------------------------- smart home sheet
  function hubLights() { return ((HUB && HUB.rooms) || []).filter(function (r) { return r.lights; }); }
  function hubItems(k) {
    if (k === "ac") return (AC && AC.zones) || [];
    if (k === "pool") return HUB && HUB.pool ? [HUB.pool] : [];
    if (k === "spk") return (HUB && HUB.speakers) || [];
    if (k === "lights") return hubLights();
    return [];
  }
  function hubMain() {
    var sh = sheet, n = sh.nav[sh.sel] || {}, f = function (i) { return sh.inMain && i === sh.item ? " focus" : ""; };
    if (n.k === "ac") { var keep = sh.zoneIdx; sh.zoneIdx = sh.inMain ? sh.item : -1; var z = zonesHtml(); sh.zoneIdx = keep; return z; }
    if (n.k === "pool") {
      var p = HUB.pool;
      return '<div class="zones"><div class="zone glass hubtile pool' + (p.heater ? " on heat" : " off") + f(0) + '"><div class="zn">' + esc(p.label || "Pool") + '</div>' +
        '<div class="hubbig">' + (p.temp != null ? p.temp + "°" : "−") + '</div><div class="st">Water now' + (p.setpoint ? " · heats to " + p.setpoint + "°" : "") + "</div>" +
        '<span class="pwr">' + (p.heater ? "Heater on" : "Heater off") + "</span></div>" +
        '<div class="panel glass hubnote"><p>' + (p.can_heat ? "The heater takes a few hours to warm the water. Turn it off when you go out." : "Ask your host if you would like the pool heated.") + "</p></div></div>";
    }
    if (n.k === "spk") return '<div class="zones">' + HUB.speakers.map(function (x, i) {
      return '<div class="zone glass hubtile' + (x.playing ? " on" : " off") + f(i) + '"><div class="zn">' + esc(x.label) + '</div>' + I.music +
        '<div class="st one">' + esc(x.playing ? x.title || "Playing" : "Paused") + '</div><div class="vol"><i style="width:' + (x.volume || 0) + '%"></i></div>' +
        '<span class="pwr">' + (x.playing ? "Playing · " : "Paused · ") + (x.volume != null ? x.volume + "%" : "") + "</span></div>";
    }).join("") + "</div>";
    if (n.k === "lights") return '<div class="zones">' + hubLights().map(function (r, i) {
      var l = r.lights;
      return '<div class="zone glass hubtile' + (l.on ? " on warm" : " off") + f(i) + '"><div class="zn">' + esc(r.label) + "</div>" + I.light +
        '<div class="st">' + (l.on && l.brightness ? l.brightness + "% bright" : l.on ? "On" : "Off") + '</div><span class="pwr">' + (l.on ? "On" : "Off") + "</span></div>";
    }).join("") + "</div>";
    return "";
  }
  function hubHint() {
    var sh = sheet, n = sh.nav[sh.sel] || {};
    if (!sh.inMain) return "<b>Up</b> and <b>down</b> to move · <b>Right</b> or <b>OK</b> to use · <b>Back</b> to close";
    var lr = hubItems(n.k).length > 1 ? "<b>Left</b> and <b>right</b> pick · " : "";
    if (n.k === "ac") return lr + "<b>Up</b> and <b>down</b> change the temperature · <b>OK</b> turns it on or off · <b>Back</b>";
    if (n.k === "pool") return HUB.pool.can_heat ? "<b>OK</b> turns the heater on or off · <b>Back</b>" : "<b>Back</b>";
    if (n.k === "spk") return lr + "<b>OK</b> play or pause · <b>Up</b> and <b>down</b> volume · <b>Back</b>";
    return lr + "<b>OK</b> turns them on or off · <b>Back</b>";
  }
  function hubKey(k) {
    var sh = sheet, n = sh.nav[sh.sel] || {}, items = hubItems(n.k);
    if (!sh.inMain) {
      if (k === "up" || k === "down") { var i = sh.navIdx + (k === "up" ? -1 : 1); if (sh.nav[i]) { sh.navIdx = sh.sel = i; sh.item = 0; } }
      else if ((k === "right" || k === "ok") && items.length) { sh.inMain = true; sh.item = 0; }
      drawSheet(); return;
    }
    if (k === "left" && sh.item === 0) { sh.inMain = false; drawSheet(); return; }
    if (k === "left" || k === "right") { sh.item = Math.max(0, Math.min(items.length - 1, sh.item + (k === "left" ? -1 : 1))); drawSheet(); return; }
    var it = items[sh.item];
    if (!it) return;
    if (n.k === "ac") {
      if ((k === "up" || k === "down") && it.can_set) { it.setpoint = Math.max(16, Math.min(30, (it.setpoint || 22) + (k === "up" ? 1 : -1))); queueSet(it, { setpoint: it.setpoint }); }
      else if (k === "ok") { it.on = !it.on; if (it.on && AC.power === "off") AC.power = "on"; queueSet(it, { on: it.on }); toast((it.label || it.name) + (it.on ? " on" : " off")); }
    } else if (n.k === "pool" && k === "ok" && it.can_heat) {
      it.heater = !it.heater; hubSend({ heater: it.heater }); toast("Pool heater " + (it.heater ? "on" : "off"));
    } else if (n.k === "spk") {
      if (k === "ok") { it.playing = !it.playing; hubSend({ speaker: it.id, action: it.playing ? "play" : "pause" }); toast(it.label + (it.playing ? " playing" : " paused")); }
      else if (k === "up" || k === "down") { it.volume = Math.max(0, Math.min(100, (it.volume || 0) + (k === "up" ? 10 : -10))); hubSend({ speaker: it.id, action: "volume", volume: it.volume }, true); }
    } else if (n.k === "lights" && k === "ok") {
      it.lights.on = !it.lights.on; hubSend({ lights: it.id, on: it.lights.on }); toast(it.label + " lights " + (it.lights.on ? "on" : "off"));
    }
    drawSheet();
  }
  var hubT = 0;
  function hubSend(body, later) {
    clearTimeout(hubT);
    var go = function () { api("hub", body).then(function (r) { if (!r.ok) toast(r.error || "That did not work"); setTimeout(refreshHub, 800); }); };
    if (later) hubT = setTimeout(go, 600); else go();
  }

  var ARC = 2 * Math.PI * 42 * 0.75;
  function zonesHtml() {
    if (!AC || !AC.connected) return '<div class="panel glass"><p class="lede">' + (AC ? "The air conditioning is not answering right now." : "Checking the air conditioning.") + "</p></div>";
    var heat = AC.mode === "heat";
    return '<div class="zones' + (AC.zones.length > 3 ? " compact" : "") + '">' + AC.zones.map(function (z, i) {
      var on = z.on && AC.power === "on", sp = z.setpoint != null ? z.setpoint : null;
      var frac = sp != null ? (sp - 16) / 14 : 0.5;
      return '<div class="zone glass' + (on ? " on" : " off") + (heat ? " heat" : "") + (i === sheet.zoneIdx ? " focus" : "") + '" data-z="' + i + '">' +
        '<div class="zn">' + esc(z.label || z.name) + '</div><div class="dial"><svg viewBox="0 0 100 100"><circle class="track" cx="50" cy="50" r="42" stroke-dasharray="' + ARC + ' 999"/>' +
        '<circle class="arc" cx="50" cy="50" r="42" stroke-dasharray="' + (ARC * frac) + ' 999"/></svg><div class="val"><b>' + (sp != null ? sp + "°" : "−") + "</b><span>" + (z.can_set ? "set to" : "fixed") + "</span></div></div>" +
        '<div class="st">' + (z.temp != null ? "Now " + z.temp + "°" : "") + '</div><span class="pwr">' + (z.on ? (AC.power === "on" ? (heat ? "Heating" : "Cooling") : "On, starting") : "Off") + "</span></div>";
    }).join("") + "</div>";
  }
  function sheetKey(k) {
    var sh = sheet;
    if (k === "back") { if (sh.inMain) { sh.inMain = false; drawSheet(); return; } closeSheet(); return; }
    if (sh.id === "climate") {
      if (!AC || !AC.connected || !AC.zones.length) return;
      var z = AC.zones[sh.zoneIdx];
      if (k === "left" || k === "right") sh.zoneIdx = Math.max(0, Math.min(AC.zones.length - 1, sh.zoneIdx + (k === "left" ? -1 : 1)));
      else if ((k === "up" || k === "down") && z.can_set) { z.setpoint = Math.max(16, Math.min(30, (z.setpoint || 22) + (k === "up" ? 1 : -1))); queueSet(z, { setpoint: z.setpoint }); }
      else if (k === "ok") { z.on = !z.on; if (z.on && AC.power === "off") AC.power = "on"; queueSet(z, { on: z.on }); toast((z.label || z.name) + (z.on ? " on" : " off")); }
      $("sheet-main").innerHTML = zonesHtml();
      return;
    }
    if (sh.id === "hub") { hubKey(k); return; }
    if (!sh.nav.length) return;
    if (k === "up" || k === "down") {
      var d = k === "up" ? -1 : 1, i = sh.navIdx + d;
      while (sh.nav[i] && sh.nav[i].group) i += d;
      if (sh.nav[i]) { sh.navIdx = i; sh.sel = i; drawSheet(); }
    }
  }
  // setpoint presses are joined for a moment so five presses send one change
  var setT = 0, setWant = {};
  function queueSet(z, change) {
    setWant[z.id] = Object.assign(setWant[z.id] || { zone: z.id }, change);
    clearTimeout(setT);
    setT = setTimeout(function () {
      var all = setWant; setWant = {};
      Object.keys(all).forEach(function (k) {
        api("aircon", all[k]).then(function (r) {
          if (!r.ok) toast(r.error || "That did not work");
          setTimeout(refreshAircon, 1200);
        });
      });
    }, 700);
  }

  // ---------------------------------------------------------------- remote keys
  var ARROWS = { ArrowLeft: "left", ArrowRight: "right", ArrowUp: "up", ArrowDown: "down" };
  var CODES = { 37: "left", 38: "up", 39: "right", 40: "down", 19: "up", 20: "down", 21: "left", 22: "right" };
  function keyOf(e) {
    if (ARROWS[e.key]) return ARROWS[e.key];
    if (CODES[e.keyCode]) return CODES[e.keyCode];
    if (e.key === "Enter" || e.key === " " || e.keyCode === 13 || e.keyCode === 23) return "ok";
    if (e.key === "Escape" || e.key === "Backspace" || e.key === "GoBack" || e.key === "BrowserBack" || e.keyCode === 27 || e.keyCode === 8 || e.keyCode === 10009 || e.keyCode === 461) return "back";
    return null;
  }
  var restT = 0, REST_MS = QS.rest ? +QS.rest * 1000 : 45000;
  function awake() {
    var was = document.body.classList.contains("rest");
    document.body.classList.remove("rest");
    clearTimeout(restT);
    restT = setTimeout(function () { if (!sheet) document.body.classList.add("rest"); }, REST_MS);
    return was;
  }
  // the couch-tv TV app keeps BACK for itself and calls tv.back() instead
  window.tv = { back: function () { if (awake()) return; if (sheet) closeSheet(); } };
  function onKey(k) {
    document.body.classList.remove("mouse");
    if (awake()) return;   // the first press only wakes the screen
    if (sheet) sheetKey(k);
    else if (k !== "back") homeKey(k);
  }
  document.addEventListener("keydown", function (e) {
    var k = keyOf(e);
    if (!k) return;
    e.preventDefault();
    onKey(k);
  });
  // the Samsung and LG app passes on keys that reached it instead of this page
  window.addEventListener("message", function (e) {
    var k = e.source === window.parent && e.data && e.data.guestKey;
    if (k === "left" || k === "right" || k === "up" || k === "down" || k === "ok" || k === "back") onKey(k);
  });

  // a mouse or a touch screen works too (handy for the preview)
  document.addEventListener("mousemove", function () { document.body.classList.add("mouse"); });
  document.addEventListener("click", function (e) {
    var t = e.target.closest ? e.target : null;
    if (!t) return;
    var card = t.closest("[data-i]"), app = t.closest("[data-a]"), nav = t.closest("[data-n]"), zone = t.closest("[data-z]");
    if (sheet && !t.closest(".sheet-in")) { closeSheet(); return; }
    if (card && !sheet) { area = "cards"; idx = +card.getAttribute("data-i"); paintFocus(); openSheet(CARDS[idx].id); }
    else if (app && !sheet) { area = "apps"; appIdx = +app.getAttribute("data-a"); paintFocus(); launch(APPS[appIdx]); }
    else if (nav && sheet) { sheet.navIdx = sheet.sel = +nav.getAttribute("data-n"); drawSheet(); }
    else if (zone && sheet && sheet.id === "hub") { sheet.inMain = true; sheet.item = +zone.getAttribute("data-z"); hubKey("ok"); }
    else if (zone && sheet) { sheet.zoneIdx = +zone.getAttribute("data-z"); sheetKey("ok"); }
  });
  document.addEventListener("wheel", function (e) {
    if (sheet && sheet.id === "climate") { e.preventDefault(); sheetKey(e.deltaY < 0 ? "up" : "down"); }
  }, { passive: false });

  // ---------------------------------------------------------------- data
  function refreshState() {
    if (BRAND) api("tv/apps").then(function (r) { BRAND_APPS = r.apps || []; if (S && !sheet) drawApps(); }, function () {});
    return api("state").then(function (s) {
      if (s.error) { $("welcome").textContent = s.error; return; }
      var first = !S || S.id !== s.id;
      S = s; HOME = s.id;
      if (first) buildScene();
      header();
      if (!sheet) drawCards();
      drawApps();
    });
  }
  function refreshWeather() {
    return fetch("/api/weather?home=" + encodeURIComponent(HOME)).then(function (r) { return r.json(); }).then(function (w) {
      WX = w; dateLine();
      if (S && !sheet) { drawCards(); drawApps(); }
    });
  }
  function refreshHub() {
    return api("hub").then(function (h) {
      if (h.error) return;
      var had = !!(HUB && (HUB.pool || (HUB.speakers || []).length));
      HUB = h;
      var has = !!(HUB.pool || (HUB.speakers || []).length);
      if (sheet && sheet.id === "hub") drawSheet();
      else if (!sheet && had !== has) drawCards();
      else refreshCard("hub");
    }, function () {});
  }
  function refreshAircon() {
    return api("aircon").then(function (a) {
      if (Object.keys(setWant).length) return;   // a change is on its way; do not jump back
      AC = a;
      if (sheet && sheet.id === "climate") { $("sheet-main").innerHTML = zonesHtml(); drawSheet(); }
      else { refreshCard("climate"); refreshCard("hub"); }
      if (sheet && sheet.id === "hub") drawSheet();
    });
  }

  // ---------------------------------------------------------------- old TV browsers
  // Samsung and LG TVs from 2021 and before (Chromium 79 and older) ignore `gap` in a flex row, so
  // tiles touch. There the gaps are put back as margins, after every change to the page.
  function flexGapWorks() {
    var d = document.createElement("div");
    d.style.cssText = "display:flex;flex-direction:column;row-gap:1px;position:absolute";
    d.appendChild(document.createElement("div"));
    d.appendChild(document.createElement("div"));
    document.body.appendChild(d);
    var ok = d.scrollHeight === 1;
    document.body.removeChild(d);
    return ok;
  }
  function fakeGaps() {
    var all = document.body.querySelectorAll("*");
    for (var i = 0; i < all.length; i++) {
      var cs = getComputedStyle(all[i]);
      if (cs.display.indexOf("flex") < 0) continue;
      var col = cs.flexDirection.indexOf("column") === 0;
      var g = parseFloat(col ? cs.rowGap : cs.columnGap) || 0;
      if (!g) continue;
      var kids = all[i].children, side = col ? "marginTop" : "marginLeft";
      for (var j = 1; j < kids.length; j++) {
        if (kids[j].getAttribute("data-gap") || !parseFloat(getComputedStyle(kids[j])[side])) {
          kids[j].style[side] = g + "px";
          kids[j].setAttribute("data-gap", "1");
        }
      }
    }
  }
  if (window.MutationObserver && !flexGapWorks()) {
    var gapT = 0;
    new MutationObserver(function () { clearTimeout(gapT); gapT = setTimeout(fakeGaps, 50); })
      .observe(document.body, { childList: true, subtree: true });
    fakeGaps();
  }

  refreshState().then(function () { refreshAircon(); refreshHub(); });
  awake();
  document.addEventListener("mousemove", awake);
  refreshWeather();
  setInterval(clock, 1000);
  setInterval(refreshState, 60000);
  setInterval(refreshWeather, 30 * 60000);
  setInterval(function () { refreshAircon(); refreshHub(); }, 20000);
  if (document.fonts) document.fonts.load("300 10px Antonio").then(function () { glassShown = ""; clock(); });
  window.addEventListener("resize", function () { glassShown = ""; clock(); });
})();
