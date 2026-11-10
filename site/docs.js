// Fetches docs/<page>.md (copied from the repo at build time) and renders it.
// Small purpose-built Markdown renderer: headings, code fences, lists, tables,
// blockquotes, hr, images, links, bold/italic/inline code. Everything is escaped first.
(function () {
  "use strict";

  var PAGES = [
    ["README", "Index"], ["installation", "Installation"], ["standalone", "Standalone"],
    ["gui", "GUI"], ["cli", "CLI"], ["spotify-setup", "Spotify setup"],
    ["configuration", "Configuration"], ["data-formats", "Data formats"], ["docker", "Docker"]
  ];
  var RAW = "https://raw.githubusercontent.com/Ssenseii/harmoni/main/";
  var imgBase = "images/";
  var REPO_BLOB ="https://github.com/Ssenseii/harmoni/blob/main/docs/guides/";

  var page = (new URLSearchParams(location.search).get("p") || "README").replace(/[^a-z0-9-]/gi, "");
  var nav = document.getElementById("docnav");
  var out = document.getElementById("doc");

  PAGES.forEach(function (p) {
    var a = document.createElement("a");
    a.href = "docs.html?p=" + p[0];
    a.textContent = p[1];
    if (p[0] === page) a.setAttribute("aria-current", "page");
    nav.appendChild(a);
  });

  function esc(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  function safeUrl(u) {
    u = u.trim();
    if (/^(https?:|mailto:|#)/i.test(u)) return u;
    if (/^[a-z][a-z0-9+.-]*:/i.test(u)) return "#"; // javascript:, data:, ...
    var m = u.match(/^(?:\.\/)?([a-z0-9-]+)\.md(#.*)?$/i);
    if (m) return "docs.html?p=" + m[1] + (m[2] || "");
    var img = u.match(/^(?:\.\.\/)+(images\/.+)$/i);
    if (img) return imgBase + img[1].slice("images/".length);
    return REPO_BLOB + u; // anything else relative: send to GitHub
  }
  function inline(s) {
    var codes = [];
    s = s.replace(/`([^`]+)`/g, function (_, c) { codes.push(c); return "\u0000" + (codes.length - 1) + "\u0000"; });
    s = esc(s);
    s = s.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, function (_, alt, u) {
      return '<img src="' + safeUrl(u) + '" alt="' + alt + '" loading="lazy">';
    });
    s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, function (_, t, u) {
      var url = safeUrl(u);
      var ext = /^https?:/i.test(url) ? ' rel="noopener"' : "";
      return '<a href="' + url + '"' + ext + ">" + t + "</a>";
    });
    s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    s = s.replace(/(^|[\s(])\*([^*\s][^*]*)\*(?=[\s).,;:]|$)/g, "$1<em>$2</em>");
    return s.replace(/\u0000(\d+)\u0000/g, function (_, i) { return "<code>" + esc(codes[+i]) + "</code>"; });
  }
  function cells(line) {
    return line.trim().replace(/^\||\|$/g, "").split("|").map(function (c) { return c.trim(); });
  }
  function slug(s) {
    return s.toLowerCase().replace(/<[^>]+>/g, "").replace(/[^\w\s-]/g, "").trim().replace(/\s+/g, "-");
  }

  function render(md) {
    md = md.replace(/ [—–] /g, ", ").replace(/[—–]/g, "-");
    var lines = md.replace(/\r\n?/g, "\n").split("\n");
    var html = [], i = 0, title = null;
    while (i < lines.length) {
      var line = lines[i], m;
      if ((m = line.match(/^```\s*(\S*)/))) {
        var code = [];
        i++;
        while (i < lines.length && !/^```/.test(lines[i])) code.push(lines[i++]);
        i++;
        html.push('<pre tabindex="0"><code>' + esc(code.join("\n")) + "</code></pre>");
      } else if ((m = line.match(/^(#{1,4})\s+(.*)$/))) {
        var n = m[1].length, txt = inline(m[2]);
        if (!title && n === 1) title = m[2];
        html.push("<h" + n + ' id="' + slug(m[2]) + '">' + txt + "</h" + n + ">");
        i++;
      } else if (/^\s*(---+|\*\*\*+)\s*$/.test(line)) {
        html.push("<hr>"); i++;
      } else if (/^\s*\|/.test(line) && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1])) {
        var head = cells(line);
        i += 2;
        var rows = [];
        while (i < lines.length && /^\s*\|/.test(lines[i])) rows.push(cells(lines[i++]));
        html.push('<div class="tablewrap" tabindex="0" role="region" aria-label="Table, scrollable"><table><thead><tr>' + head.map(function (c) { return '<th scope="col">' + inline(c) + "</th>"; }).join("") +
          "</tr></thead><tbody>" + rows.map(function (r) {
            return "<tr>" + r.map(function (c) { return "<td>" + inline(c) + "</td>"; }).join("") + "</tr>";
          }).join("") + "</tbody></table></div>");
      } else if (/^>\s?/.test(line)) {
        var q = [];
        while (i < lines.length && /^>\s?/.test(lines[i])) q.push(lines[i++].replace(/^>\s?/, ""));
        html.push("<blockquote><p>" + inline(q.join(" ")) + "</p></blockquote>");
      } else if (/^\s*([-*]|\d+\.)\s+/.test(line)) {
        var ordered = /^\s*\d+\./.test(line), items = [];
        while (i < lines.length && (/^\s*([-*]|\d+\.)\s+/.test(lines[i]) || (/^\s{2,}\S/.test(lines[i]) && items.length))) {
          var im = lines[i].match(/^(\s*)([-*]|\d+\.)\s+(.*)$/);
          if (im && im[1].length < 2) items.push({ t: im[3], kids: [] });
          else items[items.length - 1].kids.push(lines[i].trim().replace(/^([-*]|\d+\.)\s+/, ""));
          i++;
        }
        var tag = ordered ? "ol" : "ul";
        html.push("<" + tag + ">" + items.map(function (it) {
          var sub = it.kids.length ? "<ul>" + it.kids.map(function (k) { return "<li>" + inline(k) + "</li>"; }).join("") + "</ul>" : "";
          return "<li>" + inline(it.t) + sub + "</li>";
        }).join("") + "</" + tag + ">");
      } else if (!line.trim()) {
        i++;
      } else {
        var p = [];
        while (i < lines.length && lines[i].trim() && !/^(```|#{1,4}\s|>|\s*\|)/.test(lines[i]) && !/^\s*([-*]|\d+\.)\s+/.test(lines[i])) p.push(lines[i++]);
        if (!p.length) { p.push(lines[i++]); }
        html.push("<p>" + inline(p.join(" ")) + "</p>");
      }
    }
    return { html: html.join("\n"), title: title };
  }

  function get(url) {
    return fetch(url).then(function (r) {
      if (!r.ok) throw new Error(r.status);
      return r.text();
    });
  }
  // Built site: docs are served next to the page. Otherwise (for example when
  // site/docs.html is opened straight from the repo) read them from GitHub.
  get("docs/" + page + ".md").catch(function () {
    imgBase = RAW + "images/";
    return get(RAW + "docs/guides/" + page + ".md");
  }).then(function (md) {
    var res = render(md);
    out.innerHTML = res.html;
    if (res.title) document.title = res.title + " | HARMONI docs";
    out.removeAttribute("aria-live");
    if (location.hash) {
      var t = document.getElementById(location.hash.slice(1));
      if (t) t.scrollIntoView();
    }
  }).catch(function () {
    out.innerHTML = '<p>Could not load this page. <a href="' + REPO_BLOB + page + '.md">Read it on GitHub</a>.</p>';
  });
})();
