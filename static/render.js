// SafeMarkdown: turns the bot's reply (Markdown) into HTML that cannot run script.
//
// Why this exists: replies come from the model, and the model can be steered by hostile text (for example
// inside an invoice photo). A reply must never be able to put a tag, an event handler or a script into the
// page (SecurityProblems.md SP-01). The method is "escape first": every character of the input is HTML-escaped,
// and only then are the few Markdown shapes we support turned into tags we write ourselves. Raw HTML in a
// reply therefore shows up as visible text. Links are kept only for http(s) and mailto; images are never loaded.
//
// Supported: paragraphs, line breaks, **bold**, *italic*, `code`, fenced code, headings, bullet and numbered
// lists (one level), tables, block quotes, rules, links. Tested by tests/js/render_check.js.
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.SafeMarkdown = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  // The only link targets we keep. No javascript:, data:, vbscript:, protocol-relative or relative URLs.
  const SAFE_URL = /^(?:https?:\/\/|mailto:)[^\s<>"'`]*$/i;

  function emphasis(escaped) {
    return escaped
      .replace(/\*\*([^*\n]+?)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[^*\w])\*([^*\s][^*\n]*?)\*(?![*\w])/g, "$1<em>$2</em>");
  }

  function inline(raw) {
    const stash = [];
    const hold = (html) => {
      stash.push(html);
      return "\u0000" + (stash.length - 1) + "\u0000";
    };
    let s = String(raw).replace(/\u0000/g, "");
    s = s.replace(/`([^`\n]+)`/g, (_, code) => hold("<code>" + escapeHtml(code) + "</code>"));
    s = s.replace(/!\[([^\]\n]*)\]\(([^)\s]+)\)/g, (_, alt) => alt); // images: keep the alt text only
    s = s.replace(/\[([^\]\n]+)\]\(([^)\s]+)\)/g, (_, label, url) => {
      if (!SAFE_URL.test(url)) return label; // an unsafe link becomes plain text
      return hold('<a href="' + escapeHtml(url) + '" target="_blank" rel="noopener noreferrer">' + emphasis(escapeHtml(label)) + "</a>");
    });
    s = emphasis(escapeHtml(s));
    return s.replace(/\u0000(\d+)\u0000/g, (_, i) => stash[Number(i)]);
  }

  const FENCE = /^\s*```/;
  const HEADING = /^(#{1,6})\s+(.*)$/;
  const RULE = /^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/;
  const BULLET = /^\s*[-*+]\s+(.*)$/;
  const NUMBERED = /^\s*\d+[.)]\s+(.*)$/;
  const QUOTE = /^\s*>\s?(.*)$/;
  const TABLE_SEPARATOR = /^\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)*\|?\s*$/;

  function cells(line) {
    return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
  }

  function startsTable(lines, i) {
    return i + 1 < lines.length && lines[i].includes("|") && TABLE_SEPARATOR.test(lines[i + 1]) && lines[i + 1].includes("-");
  }

  function startsBlock(lines, i) {
    const line = lines[i];
    return FENCE.test(line) || HEADING.test(line) || RULE.test(line) || BULLET.test(line) || NUMBERED.test(line) ||
      QUOTE.test(line) || startsTable(lines, i);
  }

  function render(markdown) {
    const lines = String(markdown == null ? "" : markdown).replace(/\r\n?/g, "\n").split("\n");
    const out = [];
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      if (!line.trim()) { i += 1; continue; }

      if (FENCE.test(line)) {
        const code = [];
        i += 1;
        while (i < lines.length && !FENCE.test(lines[i])) { code.push(lines[i]); i += 1; }
        i += 1; // the closing fence (or the end of a reply that is still streaming)
        out.push("<pre><code>" + escapeHtml(code.join("\n")) + "</code></pre>");
        continue;
      }

      const heading = HEADING.exec(line);
      if (heading) {
        out.push("<h" + heading[1].length + ">" + inline(heading[2].trim()) + "</h" + heading[1].length + ">");
        i += 1;
        continue;
      }

      if (RULE.test(line)) { out.push("<hr>"); i += 1; continue; }

      if (startsTable(lines, i)) {
        const head = cells(lines[i]);
        i += 2;
        const rows = [];
        while (i < lines.length && lines[i].trim() && lines[i].includes("|")) { rows.push(cells(lines[i])); i += 1; }
        out.push("<table><thead><tr>" + head.map((c) => "<th>" + inline(c) + "</th>").join("") + "</tr></thead><tbody>" +
          rows.map((r) => "<tr>" + r.map((c) => "<td>" + inline(c) + "</td>").join("") + "</tr>").join("") + "</tbody></table>");
        continue;
      }

      if (BULLET.test(line) || NUMBERED.test(line)) {
        const ordered = NUMBERED.test(line) && !BULLET.test(line);
        const pattern = ordered ? NUMBERED : BULLET;
        const items = [];
        while (i < lines.length && pattern.test(lines[i])) { items.push(pattern.exec(lines[i])[1]); i += 1; }
        const tag = ordered ? "ol" : "ul";
        out.push("<" + tag + ">" + items.map((t) => "<li>" + inline(t) + "</li>").join("") + "</" + tag + ">");
        continue;
      }

      if (QUOTE.test(line)) {
        const quoted = [];
        while (i < lines.length && QUOTE.test(lines[i])) { quoted.push(QUOTE.exec(lines[i])[1]); i += 1; }
        out.push("<blockquote><p>" + quoted.map(inline).join("<br>") + "</p></blockquote>");
        continue;
      }

      const para = [line];
      i += 1;
      while (i < lines.length && lines[i].trim() && !startsBlock(lines, i)) { para.push(lines[i]); i += 1; }
      out.push("<p>" + para.map(inline).join("<br>") + "</p>");
    }
    return out.join("");
  }

  return { render, escapeHtml };
});
