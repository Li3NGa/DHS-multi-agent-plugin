import { readFile } from 'node:fs/promises'
import { spawnSync } from 'node:child_process'
import process from 'node:process'

const root = new URL('..', import.meta.url)
const packageJson = JSON.parse(await readFile(new URL('package.json', root), 'utf8'))

function run(command, args) {
  const executable = process.platform === 'win32' && command === 'pnpm' ? 'pnpm.cmd' : command
  const result = spawnSync(executable, args, { cwd: new URL(root), encoding: 'utf8', stdio: 'inherit' })
  if (result.status !== 0) process.exit(result.status ?? 1)
}

console.log(`Release candidate gate: ${packageJson.name}@${packageJson.version}`)
run('node', ['scripts/check-actions-runtime.mjs'])
run('node', ['scripts/check-native-source.mjs'])
run('node', ['scripts/check-release-contract.mjs'])
run('node', ['scripts/check-public-api.mjs'])
run('node', ['scripts/check-public-surface.mjs'])

const npm = process.platform === 'win32' ? 'npm.cmd' : 'npm'
const pack = spawnSync(npm, ['pack', '--dry-run', '--json', '--ignore-scripts'], {
  cwd: new URL(root),
  encoding: 'utf8',
})
if (pack.status !== 0) {
  process.stderr.write(pack.stderr ?? '')
  process.exit(pack.status ?? 1)
}

function extractJsonValue(text) {
  for (let start = 0; start < text.length; start += 1) {
    if (text[start] !== '[') continue
    let depth = 0
    let inString = false
    let escaped = false
    for (let index = start; index < text.length; index += 1) {
      const char = text[index]
      if (inString) {
        if (escaped) escaped = false
        else if (char === '\\') escaped = true
        else if (char === '"') inString = false
        continue
      }
      if (char === '"') {
        inString = true
        continue
      }
      if (char === '[' || char === '{') {
        depth += 1
        continue
      }
      if (char === ']' || char === '}') {
        depth -= 1
        if (depth === 0) {
          const candidate = text.slice(start, index + 1)
          try {
            return JSON.parse(candidate)
          } catch {
            break
          }
        }
        if (depth < 0) break
      }
    }
  }
  return undefined
}

const result = extractJsonValue(pack.stdout)
if (!Array.isArray(result)) {
  console.error('Release candidate pack inspection failed: npm returned no valid JSON array.')
  console.error(pack.stdout)
  process.exit(1)
}

const files = result[0]?.files?.map(file => file.path) ?? []
const required = ['dist/index.js', 'dist/types/index.d.ts', 'cordis.patch.yml']
const missing = required.filter(file => !files.includes(file))
const leaked = files.filter(file => file.startsWith('packages/') || file.startsWith('tests/'))

if (missing.length > 0 || leaked.length > 0) {
  console.error('Release candidate tarball contract failed')
  for (const file of missing) console.error(`- missing: ${file}`)
  for (const file of leaked) console.error(`- leaked source/test path: ${file}`)
  process.exit(1)
}

console.log(`Release candidate gate passed for ${packageJson.name}@${packageJson.version}.`)
console.log(`Verified tarball files: ${required.join(', ')}`)
console.log(`Tarball file count: ${files.length}`)
