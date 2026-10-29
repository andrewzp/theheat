/** Inspect actual Markdown nodes using a caller-selected, already installed parser.
 * Usage: node tests/diagnosis-markdown-safety.mjs /absolute/marked.esm.js report.md [...]
 * No renderer, browser, fetch, installation or input-derived module selection.
 */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';

const [parser, ...files] = process.argv.slice(2);
assert(parser && path.isAbsolute(parser) && files.length, 'Explicit installed parser and Markdown files required');
const {marked} = await import(pathToFileURL(parser).href);
const unsafe = [];
for (const file of files) {
  const tokens = marked.lexer(fs.readFileSync(file, 'utf8'));
  marked.walkTokens(tokens, token => {
    if (['link', 'image', 'html'].includes(token.type)) {
      unsafe.push({file, type: token.type, raw: token.raw});
    }
  });
}
console.log(JSON.stringify({files: files.length, unsafe}, null, 2));
assert.equal(unsafe.length, 0, 'Diagnosis Markdown must contain no active link, image or HTML nodes');
