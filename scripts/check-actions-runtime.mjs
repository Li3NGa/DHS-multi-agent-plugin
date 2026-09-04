import { readdir, readFile } from 'node:fs/promises'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('..', import.meta.url))
const workflowDir = join(root, '.github', 'workflows')
const forbidden = [
  /^actions\/checkout@v[1-6](?:\b|$)/,
  /^actions\/setup-node@v[1-6](?:\b|$)/,
  /^actions\/setup-python@v[1-6](?:\b|$)/,
  /^actions\/upload-artifact@v[1-6](?:\b|$)/,
  /^actions\/download-artifact@v[1-7](?:\b|$)/,
  /^softprops\/action-gh-release@v[1-2](?:\b|$)/,
]

const expected = new Map([
  ['actions/checkout', 'v7'],
  ['actions/setup-node', 'v7'],
  ['actions/setup-python', 'v7'],
  ['actions/upload-artifact', 'v7'],
  ['actions/download-artifact', 'v8'],
  ['softprops/action-gh-release', 'v3'],
])

const entries = (await readdir(workflowDir)).filter(name => /\.(?:yml|yaml)$/.test(name)).sort()
const violations = []
const seen = new Map()

for (const name of entries) {
  const content = await readFile(join(workflowDir, name), 'utf8')
  for (const rawLine of content.split(/\r?\n/)) {
    const match = rawLine.match(/^\s*(?:-\s+)?uses:\s+([^\s#]+)/)
    if (!match?.[1]) continue

    const ref = match[1]
    const action = ref.match(/^([^@]+)@(v[^\s#]+)$/)
    if (!action) continue

    const [, actionName, version] = action
    const prior = seen.get(actionName) ?? []
    prior.push(`${name}:${version}`)
    seen.set(actionName, prior)

    if (forbidden.some(pattern => pattern.test(ref))) {
      violations.push(`${name}: deprecated Node 20 action reference ${ref}`)
    }
  }
}

for (const [action, versions] of seen) {
  const expectedVersion = expected.get(action)
  if (!expectedVersion) continue

  const actualVersions = [...new Set(versions.map(item => item.slice(item.lastIndexOf(':') + 1)))]
  if (actualVersions.length !== 1 || actualVersions[0] !== expectedVersion) {
    violations.push(`${action} must use ${expectedVersion}; found ${actualVersions.join(', ')}`)
  }
}

if (violations.length > 0) {
  console.error('GitHub Actions runtime check failed:')
  for (const violation of violations) console.error(`- ${violation}`)
  process.exit(1)
}

console.log(`GitHub Actions runtime check passed across ${entries.length} workflow files.`)
for (const [action, expectedVersion] of expected) {
  if (seen.has(action)) console.log(`${action}@${expectedVersion}`)
}
