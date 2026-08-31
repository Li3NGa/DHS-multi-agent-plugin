import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

const root = new URL('..', import.meta.url)
const rootPath = decodeURIComponent(root.pathname).replace(/^\/(?:[A-Za-z]:)/, (value) => value.slice(1))

const requiredPaths = [
  'packages/dsh-multi-agent/src/index.ts',
  'packages/dsh-multi-agent/package.json',
  'dist/index.js',
]

const violations = []

for (const required of requiredPaths) {
  if (!existsSync(join(rootPath, required))) {
    violations.push(`missing production path: ${required}`)
  }
}

const sourceRoots = [
  'packages/dsh-multi-agent/src',
  'packages/dsh-multi-agent/tests',
  'scripts',
]

function walk(directory) {
  const entries = readdirSync(directory)
  for (const entry of entries) {
    const absolute = join(directory, entry)
    const info = statSync(absolute)
    if (info.isDirectory()) walk(absolute)
    else if (/\.(?:ts|tsx|mts|cts|mjs|json|yml|yaml)$/.test(entry)) {
      const relativePath = relative(rootPath, absolute).replaceAll('\\', '/')
      const text = readFileSync(absolute, 'utf8')
      if (/dsh-native/i.test(text)) {
        violations.push(`legacy Native path referenced from production-controlled file: ${relativePath}`)
      }
    }
  }
}

for (const directory of sourceRoots) {
  walk(join(rootPath, directory))
}

const packageJson = JSON.parse(readFileSync(join(rootPath, 'package.json'), 'utf8'))
const build = String(packageJson.scripts?.build ?? '')
if (!build.includes('packages/dsh-multi-agent/src/index.ts')) {
  violations.push('root build does not use packages/dsh-multi-agent/src/index.ts')
}

const patch = readFileSync(join(rootPath, 'cordis.patch.yml'), 'utf8')
if (!patch.includes('dist/index.js')) {
  violations.push('cordis.patch.yml does not point at the root release entry dist/index.js')
}

if (violations.length > 0) {
  console.error('Native source-of-truth guard failed:')
  for (const violation of violations) console.error(`- ${violation}`)
  process.exit(1)
}

console.log('Native source-of-truth guard passed.')
console.log('Production Native source: packages/dsh-multi-agent/src')
console.log('Release entry: dist/index.js')
console.log('Legacy tree: excluded from production-controlled paths')
