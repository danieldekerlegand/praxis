#!/usr/bin/env node
/**
 * Documentation structure gate — the shape of `docs/`, checked rather than remembered.
 *
 * The home of record for the rules is `rosetta/docs/reference/documentation-standard.md`
 * (a private repo, so it is cited as prose). This guard deliberately RESTATES them so it
 * stays self-contained for a repo that cannot read that one — a second copy of the prose
 * would be the drift the standard exists to prevent, but a second copy of the *checks* is
 * the point.
 *
 * R1 — THE INDEX IS THE CONTRACT. `docs/README.md` links every file under `docs/`. A file
 *      it does not link is unreachable, and unreachable documentation is worse than absent
 *      documentation: it still turns up in a grep and still reads as current.
 *      `docs/archive/` is exempt — archived documents are kept for reasoning and are
 *      deliberately not listed as current.
 *
 * R2 — EVERY DOCUMENT OPENS WITH A BANNER. The first non-heading line is
 *          > **Status:** Current · **Updated:** YYYY-MM-DD · **Owner:** <repo>
 *      `Status` is Current | Superseded | Archived | Draft and describes THE DOCUMENT, never
 *      the work it documents. Superseded and Archived must name what replaced them (or say
 *      plainly that nothing did) — checked here as "the three lines FOLLOWING the banner are
 *      not all blank". [CORRECTED 2026-09-03 — this clause was vacuous as first written: it
 *      stripped `BANNER` from the joined lines, but `BANNER` is `^…$`-anchored with no `m`
 *      flag, so it never matched a multi-line join, the banner's own text was always left
 *      behind, and the emptiness test could not fail. The rule US-3 relies on to archive a
 *      document was the one rule not actually held.]
 *
 * R3 — THE DIRECTORY SET IS CLOSED. Seven, and no others:
 *          tutorials · guides · reference · explanation · decisions · runbooks · archive
 *      A ceiling, not a quota: praxis has three of them and that is compliant. A directory
 *      outside the set must be declared, one per line, in `docs/.structure-exceptions` —
 *      which makes an exception a written decision instead of an accident.
 *
 * R4 — THE ROOT IS TIER 1 ONLY. The repo root carries README.md, CLAUDE.md, ROADMAP.md,
 *      CHANGELOG.md and LICENSE, and no other markdown. A ceiling again: praxis has no
 *      CHANGELOG.md and that is compliant. Enforced only over `*.md`, which is what the rule
 *      is actually about and what `.chief/verify.sh` / CI select this guard on. Added
 *      2026-09-03, once `technologies.md` had been archived to `docs/archive/` — US-1 left
 *      this rule out deliberately, because a gate that is red on the day it lands is a gate
 *      someone switches off. A root document that is not one of the five belongs under
 *      `docs/` if it is current and under `docs/archive/` if it is not.
 *
 * Usage: node scripts/check-docs-structure.mjs [--json]
 * Exit 0 clean, 1 on a violation.
 */
import { readFileSync, existsSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

const asJson = process.argv.includes('--json');

const ALLOWED = ['tutorials', 'guides', 'reference', 'explanation', 'decisions', 'runbooks', 'archive'];
const STATUSES = ['Current', 'Superseded', 'Archived', 'Draft'];
const BANNER = /^>\s+\*\*Status:\*\*\s+(\w+)\s+·\s+\*\*Updated:\*\*\s+(\d{4}-\d{2}-\d{2})\s+·\s+\*\*Owner:\*\*\s+(.+?)\s*$/;

const exceptions = (() => {
  try {
    return readFileSync('docs/.structure-exceptions', 'utf8').split('\n')
      .map((l) => l.split('#')[0].trim().replace(/\/$/, '')).filter(Boolean);
  } catch { return []; }
})();

function walk(dir) {
  const out = [];
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) out.push(...walk(p));
    else if (name.endsWith('.md')) out.push(p);
  }
  return out;
}

const problems = [];

// R4 — the root is Tier 1 only
const TIER1 = ['README.md', 'CLAUDE.md', 'ROADMAP.md', 'CHANGELOG.md', 'LICENSE'];
for (const name of readdirSync('.')) {
  if (!name.endsWith('.md') || TIER1.includes(name)) continue;
  if (statSync(name).isDirectory()) continue;
  problems.push(`${name} is at the repo root, which carries only ${TIER1.join(' / ')} — move it under docs/ (or docs/archive/ if it is not current)`);
}

if (!existsSync('docs/README.md')) {
  problems.push('docs/README.md is missing — there is no map');
} else {
  const docs = walk('docs').sort();
  const index = readFileSync('docs/README.md', 'utf8');
  const linked = new Set(
    [...index.matchAll(/\[[^\]]*\]\(([^)\s]+)\)/g)]
      .map((m) => m[1].split('#')[0])
      .filter((p) => p && !/^([a-z]+:|#|\/\/|\.\.)/i.test(p))
      .map((p) => join('docs', p)),
  );

  // R3 — the directory set
  for (const name of readdirSync('docs')) {
    if (!statSync(join('docs', name)).isDirectory()) continue;
    if (ALLOWED.includes(name) || exceptions.includes(name)) continue;
    problems.push(`docs/${name}/ is outside the standard's seven and is not declared in docs/.structure-exceptions`);
  }

  for (const rel of docs) {
    // R1 — the index links it
    if (rel !== 'docs/README.md' && !rel.startsWith('docs/archive/') && !linked.has(rel)) {
      problems.push(`${rel} is not linked from docs/README.md — unreachable`);
    }

    // R2 — the banner
    const lines = readFileSync(rel, 'utf8').split('\n');
    const first = lines.findIndex((l) => l.trim() && !l.startsWith('#'));
    const m = first === -1 ? null : lines[first].match(BANNER);
    if (!m) {
      problems.push(`${rel} has no 'Status · Updated · Owner' banner as its first non-heading line`);
      continue;
    }
    if (!STATUSES.includes(m[1])) {
      problems.push(`${rel} banner Status is '${m[1]}' — must be one of ${STATUSES.join(' | ')}`);
    }
    if ((m[1] === 'Superseded' || m[1] === 'Archived')
        && !lines.slice(first + 1, first + 4).join(' ').trim()) {
      problems.push(`${rel} is ${m[1]} but does not say what replaced it (or that nothing did)`);
    }
  }
}

if (asJson) {
  console.log(JSON.stringify({ problems }, null, 2));
} else if (problems.length) {
  console.error(`docs-structure: ${problems.length} violation(s)`);
  for (const p of problems) console.error(`  ${p}`);
} else {
  console.log('docs-structure: OK');
}
process.exit(problems.length ? 1 : 0);
