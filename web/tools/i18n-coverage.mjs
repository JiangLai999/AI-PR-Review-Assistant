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
      // `web/src/i18n/` 是**译文存放处**（词典里当然有中文），统计"未翻译文案"时必须排除，
      // 否则 Phase 3b 一边翻译、总量反而一边上涨（真实教训：354 → 501）。
      if (lower === 'i18n') {
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

// 判断 `/` 是"正则字面量开始"还是"除号"：看上一个有意义字符/关键字。
// 与 Esprima/TS 的词法启发式一致（够用即可，误判只会让扫描更保守）。
const REGEX_PRECEDING_CHARS = new Set([
  '(', ',', '=', ':', '[', '!', '&', '|', '?', '{', '}', ';', '+', '-', '*', '%', '^', '~', '<', '>', '',
])
const REGEX_PRECEDING_WORDS = new Set([
  'return', 'typeof', 'instanceof', 'in', 'of', 'new', 'delete', 'void', 'case', 'do', 'else', 'yield', 'await',
])

/**
 * 词法扫描源码，返回字符串/模板字面量（含所在物理行文本，供 import/export 排除）。
 *
 * 与旧版"字符流 + 只看 `//` 与块注释起点"的写法相比，这里显式处理：
 * - 行注释、块注释（含 JSX 里的大括号注释形式）；
 * - 单引号 / 双引号 / 模板字符串（含转义，模板里的 `${}` 原样保留）；
 * - **正则字面量**：`/` 是否开启正则取决于前一个有意义字符/关键字，
 *   这样路径片段与转义斜杠这类内容不会被误当成块注释而提前结束扫描；
 * - 除号（两个标识符之间的斜杠）不会被当作正则。
 */
function extractStringLiterals(code) {
  const strings = [];
  const n = code.length;
  let i = 0;
  let lastMeaningful = '';
  let lastWord = '';
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
    // regex literal（否则 `/static/*` 之类里出现的 `/*` 会被当成注释）
    if (
      c === '/' &&
      (REGEX_PRECEDING_CHARS.has(lastMeaningful) || REGEX_PRECEDING_WORDS.has(lastWord))
    ) {
      i++;
      let inClass = false;
      while (i < n) {
        const ch = code[i];
        if (ch === '\\') {
          i += 2;
          continue;
        }
        if (ch === '\n') break; // 未闭合：保守退出，按普通字符继续
        if (ch === '[') inClass = true;
        else if (ch === ']') inClass = false;
        else if (ch === '/' && !inClass) {
          i++;
          break;
        }
        i++;
      }
      while (i < n && /[a-z]/i.test(code[i])) i++; // flags
      lastMeaningful = '/';
      lastWord = '';
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
      lastMeaningful = quote;
      lastWord = '';
      continue;
    }
    if (!/\s/.test(c)) {
      lastMeaningful = c;
      if (/[A-Za-z_$]/.test(c)) lastWord += c;
      else lastWord = '';
    }
    i++;
  }
  return strings;
}

/**
 * 自测：工具必须自己先可信。以下夹具覆盖"注释里带引号/斜杠星号、JSX 注释、
 * 正则里的 `/` 与 `*`、模板插值、转义引号、除号"六种容易骗过扫描器的写法。
 * 任何一条不符 → 非零退出，避免审计结果假阴性。
 */
function selfTest() {
  const cases = [
    {
      name: '块注释里的引号与 /static/* 不参与统计',
      code: '/* 说明：路径 /static/* 与 "引号" */ const a = "保留"',
      expect: ['保留'],
    },
    {
      name: 'JSX 注释里的中文不算文案',
      code: '<div>{/* 中文注释 */}<span>{"真实文案"}</span></div>',
      expect: ['真实文案'],
    },
    {
      name: '正则字面量里的斜杠星号不吞掉后面的代码',
      code: 'const re = /\\/static\\/*/; const b = "汉字"',
      expect: ['汉字'],
    },
    {
      name: '模板字面量含插值',
      code: 'const s = `前缀 ${x} 后缀`',
      expect: ['前缀 ${x} 后缀'],
    },
    {
      name: '转义引号不提前结束字符串',
      code: "const c = '它\\'s 汉字'",
      expect: ["它\\'s 汉字"],
    },
    {
      name: '除号不被误判成正则',
      code: 'const half = a / b; const d = "汉字"',
      expect: ['汉字'],
    },
  ];
  const failures = [];
  for (const item of cases) {
    const got = extractStringLiterals(item.code)
      .map((s) => s.body)
      .filter((b) => !/^\s*(import|export)\b/.test(b))
      .filter((b) => /[\u3000-\u9fff\uff00-\uffef]/.test(b));
    const ok = got.length === item.expect.length && item.expect.every((e, idx) => got[idx] === e);
    console.log(`  ${ok ? 'PASS' : 'FAIL'}  self-test: ${item.name}${ok ? '' : ` :: got=${JSON.stringify(got)}`}`);
    if (!ok) failures.push(item.name);
  }
  return failures;
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
  // 先自测词法器：扫描器不可信时，任何"0 条"都可能是假阴性。
  const selfTestFailures = selfTest();
  if (selfTestFailures.length > 0) {
    console.error(
      `\n扫描器自测失败（${selfTestFailures.length} 条）——本次审计结果不可信，先修扫描器：\n  ` +
        selfTestFailures.join('\n  '),
    );
    process.exitCode = 2;
    return;
  }
  console.log('scanner self-test: PASS');
  console.log('');
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
