#!/usr/bin/env node
/**
 * i18n coverage audit for web/src.
 * Counts CJK-containing string literals per .ts/.tsx file, with noise excluded.
 * Read-only. Always exits 0 (audit tool, not a gate).
 * Deps: node:fs, node:path only.
 */
import fs from 'node:fs';
import path from 'node:path';

const CJK = /[\u4e00-\u9fff]/;
// pure identifiers / class lists: no spaces-with-words, no punctuation beyond class/attr tokens
const PURE_IDENT = /^[A-Za-z_][A-Za-z0-9_:-]*$/;
const PURE_CLASS_LIST = /^[A-Za-z_][A-Za-z0-9_:\-.]*(\s+[A-Za-z_][A-Za-z0-9_:\-.]*)*$/;
const IMPORT_EXPORT_LINE = /^\s*(import|export)\b/;

const scriptDir =
  typeof import.meta.dirname === 'string'
    ? import.meta.dirname
    : path.dirname(path.resolve(process.argv[1] ?? '.'));
const projectRoot = path.resolve(scriptDir, '..', '..');
const scanRoot = path.join(projectRoot, 'web', 'src');

function listSourceFiles(dir, out = []) {
  let entries;
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch {
    return out;
  }
  for (const ent of entries) {
    const full = path.join(dir, ent.name);
    if (ent.isDirectory()) {
      const lower = ent.name.toLowerCase();
      if (lower === 'docs' || lower === '__tests__' || lower === 'test' || lower === 'tests') {
        continue;
      }
      listSourceFiles(full, out);
      continue;
    }
    if (!ent.isFile()) continue;
    if (!/\.(ts|tsx)$/.test(ent.name)) continue;
    if (/\.(test|spec)\.(ts|tsx)$/.test(ent.name)) continue;
    out.push(full);
  }
  return out;
}

/**
 * Walk source and return string literal contents (unescaped-ish raw bodies).
 * Comments are skipped entirely, so comment text never reaches the caller.
 */
function extractStringLiterals(code) {
  const strings = [];
  const n = code.length;
  let i = 0;
  while (i < n) {
    const c = code[i];
    const next = i + 1 < n ? code[i + 1] : '';

    // line comment
    if (c === '/' && next === '/') {
      while (i < n && code[i] !== '\n') i++;
      continue;
    }
    // block comment
    if (c === '/' && next === '*') {
      i += 2;
      while (i < n && !(code[i] === '*' && code[i + 1] === '/')) i++;
      i = i < n ? i + 2 : n;
      continue;
    }
    // string / template
    if (c === '"' || c === "'" || c === '`') {
      const quote = c;
      let j = i + 1;
      let body = '';
      while (j < n) {
        const ch = code[j];
        if (ch === '\\') {
          // keep escape pair roughly intact; irrelevant for CJK detection
          body += ch + (j + 1 < n ? code[j + 1] : '');
          j += 2;
          continue;
        }
        if (ch === quote) break;
        if (quote !== '`' && ch === '\n') break; // unterminated; bail
        body += ch;
        j++;
      }
      // line start of the literal, for import/export line exclusion
      let lineStart = i;
      while (lineStart > 0 && code[lineStart - 1] !== '\n') lineStart--;
      let lineEnd = i;
      while (lineEnd < n && code[lineEnd] !== '\n') lineEnd++;
      const lineText = code.slice(lineStart, lineEnd);
      strings.push({ body, lineText });
      i = j < n ? j + 1 : n;
      continue;
    }
    i++;
  }
  return strings;
}

function isNoiseString(body, lineText) {
  const t = body.trim();
  if (!t) return true;
  if (IMPORT_EXPORT_LINE.test(lineText)) return true;
  if (t.startsWith('/api') || t.startsWith('#')) return true;
  if (PURE_IDENT.test(t) || PURE_CLASS_LIST.test(t)) return true;
  return false;
}

function relPosix(full) {
  return path.relative(projectRoot, full).split(path.sep).join('/');
}

function main() {
  const files = listSourceFiles(scanRoot).sort();
  const perFile = [];
  let filesWithCjk = 0;
  let literals = 0;

  for (const file of files) {
    let code;
    try {
      code = fs.readFileSync(file, 'utf8');
    } catch {
      continue;
    }
    const all = extractStringLiterals(code);
    let count = 0;
    for (const { body, lineText } of all) {
      if (isNoiseString(body, lineText)) continue;
      if (!CJK.test(body)) continue;
      count += 1;
    }
    if (count > 0) {
      filesWithCjk += 1;
      literals += count;
      perFile.push({ file: relPosix(file), count });
    }
  }

  perFile.sort((a, b) => b.count - a.count || a.file.localeCompare(b.file));
  const top = perFile.slice(0, 10).map(({ file, count }) => ({ file, count }));

  const audit = {
    files: files.length,
    filesWithCjk,
    literals,
    top,
    generatedAt: new Date().toISOString(),
  };

  console.log('i18n coverage audit');
  console.log('===================');
  console.log(`scanned root : ${relPosix(scanRoot) || 'web/src'}`);
  console.log(`files scanned: ${audit.files}`);
  console.log(`files with CJK literals: ${audit.filesWithCjk}`);
  console.log(`CJK string literals   : ${audit.literals}`);
  console.log('');
  console.log('Top 10 files by CJK literal count:');
  if (top.length === 0) {
    console.log('  (none)');
  } else {
    top.forEach((t, idx) => {
      console.log(`  ${String(idx + 1).padStart(2, ' ')}. ${t.file}  ${t.count}`);
    });
  }
  console.log('');
  console.log('I18N_AUDIT ' + JSON.stringify(audit));
}

try {
  main();
} catch (err) {
  console.error('i18n-coverage audit error (non-fatal):', err && err.message ? err.message : err);
}
process.exit(0);
