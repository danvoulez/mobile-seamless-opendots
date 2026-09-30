import test from 'node:test';
import assert from 'node:assert/strict';
import { renderMarkdown, stripMarkdown } from '../markdown.js';

test('renders the formatting assistant replies use', () => {
  assert.equal(renderMarkdown('Hello **there**, *you* and `code`'),
    '<p>Hello <strong>there</strong>, <em>you</em> and <code>code</code></p>');
  assert.equal(renderMarkdown('# Title\n\n- one\n- two\n\n3. three\n4. four'),
    '<h1>Title</h1><ul><li>one</li><li>two</li></ul><ol start="3"><li>three</li><li>four</li></ol>');
  assert.equal(renderMarkdown('```js\nconst a = 1 < 2;\n```'), '<pre><code>const a = 1 &lt; 2;</code></pre>');
  assert.equal(renderMarkdown('> quoted\n\n---'), '<blockquote><p>quoted</p></blockquote><hr>');
  assert.equal(renderMarkdown('[docs](https://example.com/a_b?x=1&y=2)'),
    '<p><a href="https://example.com/a_b?x=1&amp;y=2" target="_blank" rel="noopener noreferrer">docs</a></p>');
  assert.equal(renderMarkdown('keep snake_case_names intact'), '<p>keep snake_case_names intact</p>');
});

test('a reply still streaming renders an open fence as code', () => {
  assert.equal(renderMarkdown('Look:\n```\nline one'), '<p>Look:</p><pre><code>line one</code></pre>');
});

test('never produces markup from the text itself', () => {
  const attacks = [
    '<img src=x onerror=alert(1)>',
    '<script>alert(1)</script>',
    '[click](javascript:alert(1))',
    '[x](http://a" onmouseover="alert(1))',
    '**<b onclick=alert(1)>**',
    '`<svg onload=alert(1)>`',
    '[`x`](http://ok.example/`y`)',
    '\u00000\u0000 [a](https://e.com)',
  ];
  for (const attack of attacks) {
    const html = renderMarkdown(attack);
    assert.doesNotMatch(html, /<(img|script|svg|b)\b/i, html);
    assert.doesNotMatch(html, /\son\w+="/i, html);
    assert.doesNotMatch(html, /href="javascript:/i, html);
  }
});

test('previews are one plain line', () => {
  assert.equal(stripMarkdown('Hello! I am **Open Dots**.\n\n- item `x`'), 'Hello! I am Open Dots. - item x');
});
