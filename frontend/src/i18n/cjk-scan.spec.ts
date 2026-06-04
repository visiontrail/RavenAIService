/**
 * CJK literal scan: no Chinese/Japanese/Korean characters should appear
 * in .vue or .ts source files outside the i18n catalog files.
 *
 * The i18n/ directory itself is whitelisted because the catalog files
 * (zh.ts, en.ts) contain Chinese values by design.
 *
 * Add entries to ALLOWLIST when a file legitimately contains CJK content
 * (e.g. a fixture or a deliberate comment). Prefer extracting to the catalog
 * instead of expanding the allowlist.
 */
import { describe, it, expect } from 'vitest'
import * as fs from 'node:fs'
import * as path from 'node:path'

// CJK Unified Ideographs + Extension A + Katakana + Hiragana + Hangul
const CJK_RE = /[一-鿿㐀-䶿぀-ゟ゠-ヿ가-힯]/

// Files (relative to frontend/src) allowed to contain CJK literals.
// Prefer catalog extraction over expanding this list.
const ALLOWLIST = new Set<string>([
  'i18n/zh.ts',
  'i18n/en.ts',
  'i18n/index.ts',
  'i18n/runtime.ts',
  'i18n/catalog-parity.spec.ts',
  'i18n/cjk-scan.spec.ts',
])

function collectSourceFiles(dir: string, base: string, results: string[] = []): string[] {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const fullPath = path.join(dir, entry.name)
    const relPath = path.relative(base, fullPath)
    if (entry.isDirectory()) {
      // Skip node_modules, dist, .git, etc.
      if (['node_modules', 'dist', '.git', '__pycache__'].includes(entry.name)) continue
      collectSourceFiles(fullPath, base, results)
    } else if (
      /\.(vue|ts)$/.test(entry.name) &&
      !entry.name.endsWith('.d.ts') &&
      !entry.name.endsWith('.spec.ts')
    ) {
      results.push(relPath)
    }
  }
  return results
}

// Matches lines that are purely a comment (after optional whitespace):
//   single-line //,  JSDoc continuation * ...,  inline HTML <!-- -->,  block /* */
// These are developer notes and do not constitute user-visible hardcoded strings.
const COMMENT_RE = /^\s*(\/\/|\/\*.*\*\/|<!--.*-->|\*\s)/

function findCjkLines(filePath: string): { line: number; text: string }[] {
  const src = fs.readFileSync(filePath, 'utf8')
  const hits: { line: number; text: string }[] = []
  src.split('\n').forEach((text, idx) => {
    if (!CJK_RE.test(text)) return
    const trimmed = text.trim()
    // Skip lines that are entirely a comment.
    if (COMMENT_RE.test(trimmed)) return
    // Strip trailing inline comments before checking for CJK; if no CJK remains
    // in the code part, the line is comment-only.
    const codeOnly = trimmed.replace(/\/\/.*$/, '').replace(/\/\*.*?\*\//g, '')
    if (!CJK_RE.test(codeOnly)) return
    hits.push({ line: idx + 1, text: trimmed.slice(0, 120) })
  })
  return hits
}

describe('CJK literal scan', () => {
  const srcRoot = path.resolve(__dirname, '..')
  const files = collectSourceFiles(srcRoot, srcRoot)

  const violations: string[] = []
  for (const rel of files) {
    if (ALLOWLIST.has(rel)) continue
    const hits = findCjkLines(path.join(srcRoot, rel))
    for (const { line, text } of hits) {
      violations.push(`${rel}:${line}  →  ${text}`)
    }
  }

  it('no .vue/.ts files outside i18n/ contain hardcoded CJK text', () => {
    expect(
      violations,
      violations.length
        ? `Found ${violations.length} CJK literal(s):\n\n${violations.join('\n')}\n\nExtract these strings into zh.ts / en.ts.`
        : '',
    ).toHaveLength(0)
  })
})
