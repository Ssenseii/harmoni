(function () {
  "use strict";

  var REPO = "Ssenseii/harmoni";
  var API = "https://api.github.com/repos/" + REPO + "/releases?per_page=100";
  var PLATFORMS = {
    windows: { label: "Windows", note: "" },
    macos: { label: "macOS", note: "Apple Silicon" },
    linux: { label: "Linux", note: "" }
  };
  var HOWTO = {
    windows: [
      "Extract the ZIP to any folder.",
      "Run <code>Harmoni.exe</code>. If SmartScreen warns, click <b>More info</b> then <b>Run anyway</b> (the app is unsigned).",
      "Drag an Exportify CSV into the window."
    ],
    macos: [
      "Open the DMG and drag HARMONI to Applications.",
      "First launch: right-click the app, choose <b>Open</b>, then <b>Open</b> again (the app is unsigned).",
      "Still blocked? Run <code>xattr -cr /Applications/HARMONI.app</code> in Terminal."
    ],
    linux: [
      "Extract: <code>tar -xzf Harmoni-Linux.tar.gz</code>",
      "Make it executable if needed: <code>chmod +x Harmoni</code>",
      "Run it from the extracted folder."
    ]
  };

  /* ---------- theme ---------- */
  var root = document.documentElement;
  var themeBtn = document.getElementById("theme");
  function currentTheme() {
    var t = root.getAttribute("data-theme");
    if (t) return t;
    return window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  function paintThemeBtn() {
    if (themeBtn) themeBtn.textContent = currentTheme() === "dark" ? "Light mode" : "Dark mode";
  }
  if (themeBtn) {
    themeBtn.addEventListener("click", function () {
      var next = currentTheme() === "dark" ? "light" : "dark";
      root.setAttribute("data-theme", next);
      try { localStorage.setItem("theme", next); } catch (e) {}
      paintThemeBtn();
    });
    paintThemeBtn();
  }

  var primary = document.getElementById("primary");
  if (!primary) return; // docs page: theme only

  /* ---------- helpers ---------- */
  function detectOS() {
    var ua = navigator.userAgent || "";
    var plat = (navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || "";
    if (/android|iphone|ipad|ipod/i.test(ua)) return "mobile";
    if (/win/i.test(plat) || /windows/i.test(ua)) return "windows";
    if (/mac/i.test(plat) || /mac os/i.test(ua)) return "macos";
    if (/linux|x11|cros/i.test(plat + ua)) return "linux";
    return null;
  }
  function classify(name) {
    var n = name.toLowerCase();
    if (/\.(exe|msi)$/.test(n) || /windows|win64|win32/.test(n)) return "windows";
    if (/\.(dmg|pkg)$/.test(n) || /mac/.test(n)) return "macos";
    if (/linux|\.appimage$|\.deb$|\.rpm$/.test(n)) return "linux";
    return null;
  }
  function size(bytes) {
    return (bytes / 1048576).toFixed(1) + " MB";
  }
  function day(iso) {
    return (iso || "").slice(0, 10);
  }
  function el(tag, props, kids) {
    var e = document.createElement(tag);
    for (var k in props || {}) {
      if (k === "text") e.textContent = props[k];
      else if (k === "html") e.innerHTML = props[k];
      else e.setAttribute(k, props[k]);
    }
    (kids || []).forEach(function (c) { e.appendChild(c); });
    return e;
  }

  /* ---------- data ---------- */
  function getJSON(url) {
    return fetch(url, { headers: { Accept: "application/json" } }).then(function (r) {
      if (!r.ok) throw new Error(url + " -> " + r.status);
      return r.json();
    });
  }
  // Prefer the snapshot built with the site (no rate limit); fall back to the live API.
  function load() {
    return getJSON("releases.json")
      .then(function (d) { if (!d.releases || !d.releases.length) throw new Error("empty"); return d; })
      .catch(function () {
        return getJSON(API).then(function (list) { return { generated: null, releases: list }; });
      });
  }
  function normalize(raw) {
    var out = [];
    raw.forEach(function (r) {
      if (r.draft) return;
      var files = [];
      (r.assets || []).forEach(function (a) {
        var p = classify(a.name);
        if (!p) return;
        files.push({ platform: p, name: a.name, size: a.size, url: a.browser_download_url });
      });
      if (!files.length) return;
      out.push({
        tag: r.tag_name, date: r.published_at || r.created_at, url: r.html_url,
        pre: !!r.prerelease, files: files
      });
    });
    out.sort(function (a, b) { return a.date < b.date ? 1 : -1; });
    return out;
  }

  /* ---------- render ---------- */
  var releases = [], filter = "all", os = detectOS();

  function renderPrimary() {
    var latest = releases.filter(function (r) { return !r.pre; })[0] || releases[0];
    primary.innerHTML = "";
    if (!latest) {
      primary.appendChild(el("p", { html: 'No releases found. See the <a href="https://github.com/' + REPO + '/releases">releases page</a>.' }));
      return;
    }
    var mine = PLATFORMS[os] && latest.files.filter(function (f) { return f.platform === os; })[0];
    var verLine = "Latest version: " + latest.tag + " (" + day(latest.date) + ")";

    if (mine) {
      primary.appendChild(el("a", { class: "btn", href: mine.url, text: "Download for " + PLATFORMS[os].label }));
      primary.appendChild(el("p", { class: "small muted", text: verLine + " · " + mine.name + " · " + size(mine.size) }));
    } else {
      var msg = os === "mobile"
        ? "HARMONI is a desktop app. Open this page on a computer, or pick a platform below."
        : "Pick your platform:";
      primary.appendChild(el("p", { text: msg }));
      primary.appendChild(el("p", { class: "small muted", text: verLine }));
    }

    var others = el("p", { class: "others" });
    others.appendChild(document.createTextNode(mine ? "Other platforms: " : ""));
    latest.files.forEach(function (f) {
      if (mine && f.platform === os) return;
      var label = PLATFORMS[f.platform].label + (PLATFORMS[f.platform].note ? " (" + PLATFORMS[f.platform].note + ")" : "");
      others.appendChild(el("a", { href: f.url, text: label + " · " + size(f.size) }));
    });
    primary.appendChild(others);

    var howto = document.getElementById("howto");
    if (mine && HOWTO[os]) {
      howto.hidden = false;
      howto.innerHTML = "<h3>After downloading (" + PLATFORMS[os].label + ")</h3><ol>" +
        HOWTO[os].map(function (s) { return "<li>" + s + "</li>"; }).join("") + "</ol>" +
        '<p class="small muted">Full instructions and troubleshooting: <a href="docs.html?p=standalone">standalone guide</a>.</p>';
    }
  }

  function renderTable() {
    var body = document.querySelector("#table tbody");
    body.innerHTML = "";
    var firstStable = releases.filter(function (r) { return !r.pre; })[0];
    var rows = 0;
    releases.forEach(function (r) {
      r.files.forEach(function (f) {
        if (filter !== "all" && f.platform !== filter) return;
        rows++;
        var tr = el("tr", r === firstStable ? { class: "latest" } : {});
        var ver = el("td", {}, [el("span", { class: "tag", text: r.tag })]);
        if (r === firstStable) ver.appendChild(el("span", { class: "pill", text: "latest" }));
        if (r.pre) ver.appendChild(el("span", { class: "pill", text: "pre-release" }));
        tr.appendChild(ver);
        tr.appendChild(el("td", { text: day(r.date) }));
        tr.appendChild(el("td", { text: PLATFORMS[f.platform].label }));
        tr.appendChild(el("td", {}, [el("a", { href: f.url, "aria-label": f.name + " " + r.tag, text: f.name })]));
        tr.appendChild(el("td", { class: "num", text: size(f.size) }));
        tr.appendChild(el("td", {}, [el("a", { href: r.url, "aria-label": "Release notes for " + r.tag, text: "notes" })]));
        body.appendChild(tr);
      });
    });
    var st = document.getElementById("status");
    if (st) st.textContent = "Showing " + rows + (rows === 1 ? " file" : " files") + (filter === "all" ? " for all platforms." : " for " + PLATFORMS[filter].label + ".");
    if (!rows) body.appendChild(el("tr", {}, [el("td", { colspan: "6", class: "muted", text: "No files for this platform." })]));
  }

  function setFilter(f) {
    filter = f;
    Array.prototype.forEach.call(document.querySelectorAll(".filters button"), function (b) {
      b.setAttribute("aria-pressed", String(b.getAttribute("data-f") === f));
    });
    renderTable();
  }
  Array.prototype.forEach.call(document.querySelectorAll(".filters button"), function (b) {
    b.addEventListener("click", function () { setFilter(b.getAttribute("data-f")); });
  });

  load().then(function (data) {
    releases = normalize(data.releases);
    renderPrimary();
    renderTable();
    if (data.generated) {
      document.getElementById("updated").textContent = " · release list updated " + day(data.generated);
    }
  }).catch(function () {
    primary.innerHTML = '<p>Could not load the release list. Get the files directly from the ' +
      '<a href="https://github.com/' + REPO + '/releases/latest">latest release page</a>.</p>';
    document.querySelector("#table tbody").innerHTML =
      '<tr><td colspan="6"><a href="https://github.com/' + REPO + '/releases">Open all releases on GitHub</a></td></tr>';
  });
})();
