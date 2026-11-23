// Checks for static/render.js, the Markdown renderer for the bot's replies (SecurityProblems.md SP-01).
// Run by tests/test_render_js.py with plain Node; no packages needed. Exits non-zero on the first failure.
const assert = require("node:assert/strict");
const path = require("node:path");

const { render } = require(path.join(__dirname, "..", "..", "static", "render.js"));

const cases = [];
const check = (name, fn) => cases.push([name, fn]);
const noTag = (html, tag) => assert.ok(!new RegExp(`<${tag}[\\s>/]`, "i").test(html), `unexpected <${tag}> in: ${html}`);

// ---- hostile input is shown as text, never run ----
check("raw img with onerror is escaped", () => {
  const html = render('<img src=x onerror="alert(1)">');
  noTag(html, "img");
  assert.match(html, /&lt;img/);
});
check("script tag is escaped", () => {
  const html = render("<script>alert(1)</script>");
  noTag(html, "script");
  assert.match(html, /&lt;script&gt;/);
});
check("svg, iframe, style, a with handler are all escaped", () => {
  for (const raw of ["<svg onload=alert(1)>", "<iframe src=javascript:alert(1)></iframe>", "<style>*{}</style>",
                     '<a href="x" onmouseover="alert(1)">hi</a>', '"><svg onload=1>']) {
    const html = render(raw);
    for (const tag of ["svg", "iframe", "style"]) noTag(html, tag);
    assert.ok(!/<a [^>]*onmouseover/i.test(html), html);
    assert.ok(!/<[a-z]+[^>]*\son[a-z]+=/i.test(html), html);
  }
});
check("javascript: links lose their link", () => {
  for (const url of ["javascript:alert(1)", "JaVaScRiPt:alert(1)", " javascript:alert(1)", "java\tscript:alert(1)",
                     "data:text/html,<script>alert(1)</script>", "vbscript:x", "//evil.example/x", "/relative"]) {
    const html = render(`[click me](${url})`);
    assert.ok(!/<a[\s>]/i.test(html), `link kept for ${JSON.stringify(url)}: ${html}`);
    assert.match(html, /click me/);
  }
});
check("http, https and mailto links are kept, hardened", () => {
  const html = render("[ok](https://example.com/a?b=1&c=2)");
  assert.match(html, /<a href="https:\/\/example\.com\/a\?b=1&amp;c=2"/);
  assert.match(html, /rel="noopener noreferrer"/);
  assert.match(html, /target="_blank"/);
  assert.match(render("[mail](mailto:a@b.co)"), /<a href="mailto:a@b\.co"/);
});
check("a quote in a link cannot break out of the attribute", () => {
  const html = render('[x](https://a.com/"onmouseover="alert(1))');
  assert.ok(!/onmouseover="/.test(html.replace(/&quot;/g, "")), html);
  assert.ok(!/<a [^>]*" onmouseover/i.test(html), html);
});
check("markdown images are not loaded", () => {
  const html = render("![x](https://evil.example/p.png)");
  noTag(html, "img");
});
check("code is escaped, not interpreted", () => {
  const html = render("`<b>x</b>`\n\n```\n<script>1</script>\n```");
  noTag(html, "b");
  noTag(html, "script");
  assert.match(html, /<code>&lt;b&gt;x&lt;\/b&gt;<\/code>/);
  assert.match(html, /<pre><code>&lt;script&gt;1&lt;\/script&gt;/);
});
check("half-written replies (streaming) never produce unsafe output", () => {
  for (const partial of ["**bo", "| a | b", "| a | b |\n|---", "```\ncode", "[x](", "[x](https://a", "- ", "<scr", "<img src=x onerror=a"]) {
    const html = render(partial);
    assert.equal(typeof html, "string");
    assert.ok(!/<(script|img|svg|iframe)[\s>]/i.test(html), `${JSON.stringify(partial)} -> ${html}`);
  }
});

// ---- ordinary replies still look right ----
check("bold, italic, inline code", () => {
  const html = render("**bold** and *it* and `code`");
  assert.match(html, /<strong>bold<\/strong>/);
  assert.match(html, /<em>it<\/em>/);
  assert.match(html, /<code>code<\/code>/);
});
check("headings", () => {
  assert.match(render("## Title"), /<h2>Title<\/h2>/);
});
check("lists", () => {
  assert.match(render("- a\n- b"), /<ul><li>a<\/li><li>b<\/li><\/ul>/);
  assert.match(render("1. a\n2. b"), /<ol><li>a<\/li><li>b<\/li><\/ol>/);
});
check("tables", () => {
  const html = render("| Product | Revenue |\n|---|---|\n| Challah | 312 |\n| Rye | 40 |");
  assert.match(html, /<table>/);
  assert.match(html, /<th>Product<\/th>/);
  assert.match(html, /<td>312<\/td>/);
  assert.match(html, /<td>Rye<\/td>/);
});
check("paragraphs and line breaks", () => {
  assert.match(render("one\n\ntwo"), /<p>one<\/p>\s*<p>two<\/p>/);
  assert.match(render("line1\nline2"), /line1<br>line2/);
});
check("special characters survive, escaped once", () => {
  const html = render("Revenue: ₪1,240 & more < 5 > 2");
  assert.match(html, /₪1,240 &amp; more &lt; 5 &gt; 2/);
  assert.ok(!html.includes("&amp;amp;"));
});
check("Hebrew text is untouched", () => {
  assert.match(render("**חלה** נמכרה הכי הרבה"), /<strong>חלה<\/strong> נמכרה הכי הרבה/);
});

let failed = 0;
for (const [name, fn] of cases) {
  try {
    fn();
    console.log(`ok   ${name}`);
  } catch (err) {
    failed += 1;
    console.log(`FAIL ${name}\n     ${String(err.message).split("\n")[0]}`);
  }
}
console.log(`\n${cases.length - failed}/${cases.length} passed`);
process.exit(failed ? 1 : 0);
