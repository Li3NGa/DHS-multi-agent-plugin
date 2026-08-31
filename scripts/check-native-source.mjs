import { lstatSync, readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const rootPath = fileURLToPath(new URL('..', import.meta.url))
const violations = []

const requiredPaths = [
  'packages/dsh-multi-agent/src/index.ts',
  'packages/dsh-multi-agent/package.json',
  'packages/dsh-multi-agent/tsconfig.build.json',
  'cordis.patch.yml',
]

for (const required of requiredPaths) {
  try {
    statSync(join(rootPath, required))
  } catch {
    violations.push(`missing production path: ${required}`)
  }
}

// Only inspect production source and tests. The test tree contains a small
// compatibility bridge named `tests/src`; do not follow symlinked directories.
const sourceRoots = [
  'packages/dsh-multi-agent/src',
  'packages/dsh-multi-agent/tests',
]

function walk(directory) {
  for (const entry of readdirSync(directory)) {
    const absolute = join(directory, entry)
    const lstat = lstatSync(absolute)
    if (lstat.isSymbolicLink()) continue
    if (lstat.isDirectory()) {
      walk(absolute)
      continue
    }
    if (!/\.(?:ts|tsx|mts|cts|mjs|json|yml|yaml)$/.test(entry)) continue
    const relativePath = relative(rootPath, absolute).replaceAll('\\', '/')
    const text = readFileSync(absolute, 'utf8')
    if (/dsh-native[\\/]/i.test(text)) {
      violations.push(`legacy Native path referenced from production-controlled file: ${relativePath}`)
    }
  }
}

for (const directory of sourceRoots) walk(join(rootPath, directory))

const packageJson = JSON.parse(readFileSync(join(rootPath, 'package.json'), 'utf8'))
const build = String(packageJson.scripts?.build ?? '')
const buildJs = String(packageJson.scripts?.['build:js'] ?? '')
if (!buildJs.includes('packages/dsh-multi-agent/src/index.ts')) {
  violations.push('root build:js does not use packages/dsh-multi-agent/src/index.ts')
}
if (!build.includes('build:js') || !build.includes('build:types')) {
  violations.push('root build must invoke both build:js and build:types')
}
if (packageJson.main !== './dist/index.js') {
  violations.push(`root package main must be ./dist/index.js (got ${String(packageJson.main)})`)
}
if (packageJson.types !== './dist/types/index.d.ts') {
  violations.push(`root package types must be ./dist/types/index.d.ts (got ${String(packageJson.types)})`)
}
if (packageJson.exports?.['.']?.import !== './dist/index.js') {
  violations.push('root package exports.import must be ./dist/index.js')
}
if (packageJson.exports?.['.']?.types !== './dist/types/index.d.ts') {
  violations.push('root package exports.types must be ./dist/types/index.d.ts')
}
if (packageJson.dsh?.bundle?.patch !== './cordis.patch.yml') {
  violations.push('root package dsh.bundle.patch must be ./cordis.patch.yml')
}
if (!packageJson.files?.includes('cordis.patch.yml')) {
  violations.push('root package files must include cordis.patch.yml')
}

if (violations.length > 0) {
  console.error('Native source-of-truth guard failed:')
  for (const violation of violations) console.error(`- ${violation}`)
  process.exit(1)
}

console.log('Native source-of-truth guard passed.')
console.log('Production Native source: packages/dsh-multi-agent/src')
console.log('Release entry: dist/index.js')
console.log('Type declarations: dist/types/index.d.ts')
console.log('DSH bundle patch: cordis.patch.yml')
console.log('Legacy tree: excluded from production-controlled paths')
