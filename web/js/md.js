/* Minimal, safe Markdown renderer for chat messages.
   Escapes HTML first, then applies a conservative subset: code fences,
   inline code, bold/italic, links (http/https only), headings, lists,
   blockquotes, horizontal rules. No raw HTML passes through. */
"use strict";

const Markdown = (() => {
  function escapeHtml(text) {
    return text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function inline(text) {
    text = escapeHtml(text);  // escape first: no raw HTML can survive
    // order matters: code first (no markdown inside), then bold/italic, links last
    text = text.replace(/`([^`\n]+)`/g, (_, code) =>
      `<code>${code}</code>`);
    text = text.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
    text = text.replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
    text = text.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
    return text;
  }

  function render(src) {
    if (!src) return "";
    const lines = String(src).split("\n");
    const out = [];
    let inCode = false;
    let codeBuf = [];
    let listBuf = null; // {ordered: bool, items: []}

    function flushList() {
      if (!listBuf) return;
      const tag = listBuf.ordered ? "ol" : "ul";
      const items = listBuf.items.map((item) => `<li>${inline(item)}</li>`).join("");
      out.push(`<${tag}>${items}</${tag}>`);
      listBuf = null;
    }

    for (const raw of lines) {
      const line = raw;
      if (line.trim().startsWith("```")) {
        if (inCode) {
          out.push(`<pre><code>${escapeHtml(codeBuf.join("\n"))}</code></pre>`);
          codeBuf = [];
          inCode = false;
        } else {
          flushList();
          inCode = true;
        }
        continue;
      }
      if (inCode) {
        codeBuf.push(line);
        continue;
      }
      const trimmed = line.trim();
      if (trimmed === "") {
        flushList();
        continue;
      }
      const heading = trimmed.match(/^(#{1,6})\s+(.*)$/);
      if (heading) {
        flushList();
        const level = Math.min(heading[1].length, 6);
        out.push(`<h${level}>${inline(heading[2])}</h${level}>`);
        continue;
      }
      if (/^(-{3,}|\*{3,})$/.test(trimmed)) {
        flushList();
        out.push("<hr>");
        continue;
      }
      if (trimmed.startsWith("> ")) {
        flushList();
        out.push(`<blockquote>${inline(trimmed.slice(2))}</blockquote>`);
        continue;
      }
      const ul = trimmed.match(/^[-*+]\s+(.*)$/);
      const ol = trimmed.match(/^\d+[.)]\s+(.*)$/);
      if (ul) {
        if (!listBuf || listBuf.ordered) { flushList(); listBuf = { ordered: false, items: [] }; }
        listBuf.items.push(ul[1]);
        continue;
      }
      if (ol) {
        if (!listBuf || !listBuf.ordered) { flushList(); listBuf = { ordered: true, items: [] }; }
        listBuf.items.push(ol[1]);
        continue;
      }
      flushList();
      out.push(`<p>${inline(trimmed)}</p>`);
    }
    flushList();
    if (inCode) {
      out.push(`<pre><code>${escapeHtml(codeBuf.join("\n"))}</code></pre>`);
    }
    return out.join("");
  }

  return { render, escapeHtml };
})();
