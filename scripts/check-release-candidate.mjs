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

// npm may emit lifecycle/build messages before its JSON result even with
// --ignore-scripts. Extract the final JSON array instead of assuming stdout is
// machine-readable from byte zero.
const jsonStarts = [...pack.stdout.matchAll(/\[\s*\{/g)].map(match => match.index ?? -1).filter(index => index >= 0)
const jsonStart = jsonStarts.at(-1)
if (jsonStart === undefined) {
  console.error('Release candidate pack inspection failed: npm returned no JSON result.')
  console.error(pack.stdout)
  process.exit(1)
}

let result
try {
  result = JSON.parse(pack.stdout.slice(jsonStart))
} catch (error) {
  console.error('Release candidate pack inspection failed: invalid npm JSON result.')
  console.error(error instanceof Error ? error.message : String(error))
  process.exit(1)
}

const files = result[0]?.files?.map(file => file.path) ?? []
const required = ['dist/index.js', 'dist/types/index.d.ts', 'cordis.patch.yml']
const missing = required.filter(file => !files.includes(file))
const leaked = files.filter(file => file.startsWith('packages/') || file.startsWith('tests/'))

if (missing.length > 0 || leaked.length > 0) {
  console.error('Release candidate tarball contract failed.')
  for (const file of missing) console.error(`- missing: ${file}`)
  for (const file of leaked) console.error(`- leaked source/test path: ${file}`)
  process.exit(1)
}

console.log(`Release candidate gate passed for ${packageJson.name}@${packageJson.version}.`)
console.log(`Verified tarball files: ${required.join(', ')}`)
console.log(`Tarball file count: ${files.length}`)
