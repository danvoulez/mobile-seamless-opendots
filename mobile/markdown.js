// A small Markdown renderer for assistant replies.
//
// Everything is HTML-escaped first; the only markup in the output is the
// markup produced here. Covers what the Mac client renders: paragraphs,
// headings, lists, block quotes, rules, fenced and inline code, bold, italic
// and http(s)/mailto links. Unclosed fences (a reply still streaming) render
// as code up to the end.

const ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };

export function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ESCAPES[char]);
}

const FENCE = /^\s*(`{3,}|~{3,})\s*([\w+#.-]*)\s*$/;
const HEADING = /^(#{1,6})\s+(.*?)\s*#*\s*$/;
const RULE = /^\s*([-*_])(\s*\1){2,}\s*$/;
const QUOTE = /^\s*>/;
const LIST_ITEM = /^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$/;

function isBlockStart(line) {
  return FENCE.test(line) || HEADING.test(line) || RULE.test(line) || QUOTE.test(line) || LIST_ITEM.test(line);
}

function inline(text) {
  const spans = [];
  const hold = (html) => `\u0000${spans.push(html) - 1}\u0000`;

  let html = text.replace(/`([^`\n]+)`/g, (_, code) => hold(`<code>${escapeHtml(code)}</code>`));
  html = escapeHtml(html);
  html = html.replace(/\[([^\]\n]+)\]\(([^)\s\u0000]+)\)/g, (match, label, url) => (
    /^(https?:\/\/|mailto:)/i.test(url)
      ? hold(`<a href="${url}" target="_blank" rel="noopener noreferrer">${label}</a>`)
      : label
  ));
  html = html
    .replace(/\*\*(?=\S)([\s\S]*?\S)\*\*/g, '<strong>$1</strong>')
    .replace(/__(?=\S)([\s\S]*?\S)__/g, '<strong>$1</strong>')
    .replace(/(^|[^*\w])\*(?=[^\s*])([^*\n]*?[^\s*])\*(?![*\w])/g, '$1<em>$2</em>')
    .replace(/(^|[^_\w])_(?=[^\s_])([^_\n]*?[^\s_])_(?![_\w])/g, '$1<em>$2</em>');

  // Restore held spans; a link label may itself hold a code span.
  const restore = (value) => value.replace(/\u0000(\d+)\u0000/g, (_, index) => restore(spans[Number(index)]));
  return restore(html);
}

export function renderMarkdown(source) {
  const lines = String(source ?? '').replace(/\u0000/g, '').replace(/\r\n?/g, '\n').split('\n');
  const out = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    const fence = line.match(FENCE);
    if (fence) {
      const marker = fence[1];
      const body = [];
      i += 1;
      while (i < lines.length && !lines[i].trim().startsWith(marker)) {
        body.push(lines[i]);
        i += 1;
      }
      i += 1;
      out.push(`<pre><code>${escapeHtml(body.join('\n'))}</code></pre>`);
      continue;
    }

    if (!line.trim()) {
      i += 1;
      continue;
    }

    const heading = line.match(HEADING);
    if (heading) {
      const level = heading[1].length;
      out.push(`<h${level}>${inline(heading[2])}</h${level}>`);
      i += 1;
      continue;
    }

    if (RULE.test(line)) {
      out.push('<hr>');
      i += 1;
      continue;
    }

    if (QUOTE.test(line)) {
      const body = [];
      while (i < lines.length && QUOTE.test(lines[i])) {
        body.push(lines[i].replace(/^\s*>\s?/, ''));
        i += 1;
      }
      out.push(`<blockquote>${renderMarkdown(body.join('\n'))}</blockquote>`);
      continue;
    }

    const first = line.match(LIST_ITEM);
    if (first) {
      const ordered = /\d/.test(first[2]);
      const items = [];
      while (i < lines.length) {
        const item = lines[i].match(LIST_ITEM);
        if (item && /\d/.test(item[2]) === ordered) {
          items.push(item[3]);
        } else if (items.length && lines[i].trim() && /^\s{2,}/.test(lines[i]) && !item) {
          items[items.length - 1] += `\n${lines[i].trim()}`;
        } else {
          break;
        }
        i += 1;
      }
      const tag = ordered ? 'ol' : 'ul';
      const start = ordered ? parseInt(first[2], 10) : 1;
      const startAttr = ordered && start !== 1 ? ` start="${start}"` : '';
      out.push(`<${tag}${startAttr}>${items.map((item) => `<li>${inline(item)}</li>`).join('')}</${tag}>`);
      continue;
    }

    const paragraph = [];
    while (i < lines.length && lines[i].trim() && (paragraph.length === 0 || !isBlockStart(lines[i]))) {
      paragraph.push(lines[i]);
      i += 1;
    }
    out.push(`<p>${inline(paragraph.join('\n'))}</p>`);
  }

  return out.join('');
}

// Plain one-line text for list previews.
export function stripMarkdown(source) {
  return String(source ?? '')
    .replace(/```[\s\S]*?(```|$)/g, ' ')
    .replace(/`([^`]*)`/g, '$1')
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/[*_#>~]+/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}
