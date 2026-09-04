import { readdir, readFile } from 'node:fs/promises'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('..', import.meta.url))
const workflowDir = join(root, '.github', 'workflows')

const expected = new Map([
  ['actions/checkout', {
    sha: '3d3c42e5aac5ba805825da76410c181273ba90b1',
    version: 'v7.0.1',
  }],
  ['actions/setup-node', {
    sha: '820762786026740c76f36085b0efc47a31fe5020',
    version: 'v7.0.0',
  }],
  ['actions/setup-python', {
    sha: '5fda3b95a4ea91299a34e894583c3862153e4b97',
    version: 'v7.0.0',
  }],
  ['actions/upload-artifact', {
    sha: '043fb46d1a93c77aae656e7c1c64a875d1fc6a0a',
    version: 'v7.0.1',
  }],
  ['actions/download-artifact', {
    sha: '3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c',
    version: 'v8.0.1',
  }],
  ['pypa/gh-action-pypi-publish', {
    sha: 'dc37677b2e1c63e2034f94d8a5b11f265b73ba33',
    version: 'v1.14.2',
  }],
  ['softprops/action-gh-release', {
    sha: '3d0d9888cb7fd7b750713d6e236d1fcb99157228',
    version: 'v3.0.2',
  }],
])

const entries = (await readdir(workflowDir)).filter(name => /\.(?:yml|yaml)$/.test(name)).sort()
const violations = []
const seen = new Map()

for (const name of entries) {
  const content = await readFile(join(workflowDir, name), 'utf8')
  for (const [index, rawLine] of content.split(/\r?\n/).entries()) {
    const match = rawLine.match(/^\s*(?:-\s+)?uses:\s+([^#\s]+)(?:\s+#\s*(.*))?$/)
    if (!match?.[1]) continue

    const ref = match[1]
    if (ref.startsWith('./')) continue

    const action = ref.match(/^([^@]+)@([^\s]+)$/)
    if (!action) {
      violations.push(`${name}:${index + 1}: invalid external action reference ${ref}`)
      continue
    }

    const [, actionName, versionOrSha] = action
    const expectedAction = expected.get(actionName)
    if (!expectedAction) {
      violations.push(`${name}:${index + 1}: unapproved external action ${actionName}`)
      continue
    }

    if (!/^[0-9a-f]{40}$/i.test(versionOrSha)) {
      violations.push(`${name}:${index + 1}: ${actionName} must be pinned to a 40-character commit SHA`)
      continue
    }

    if (versionOrSha.toLowerCase() !== expectedAction.sha.toLowerCase()) {
      violations.push(`${name}:${index + 1}: ${actionName} is pinned to ${versionOrSha}, expected ${expectedAction.sha}`)
    }

    if ((match[2] ?? '').trim() !== expectedAction.version) {
      violations.push(`${name}:${index + 1}: ${actionName} must include version comment # ${expectedAction.version}`)
    }

    const prior = seen.get(actionName) ?? []
    prior.push(`${name}:${index + 1}`)
    seen.set(actionName, prior)
  }
}

for (const [action, expectedAction] of expected) {
  if (!seen.has(action)) {
    violations.push(`${action}@${expectedAction.version} is required but was not found in workflows`)
  }
}

if (violations.length > 0) {
  console.error('GitHub Actions supply-chain check failed:')
  for (const violation of violations) console.error(`- ${violation}`)
  process.exit(1)
}

console.log(`GitHub Actions supply-chain check passed across ${entries.length} workflow files.`)
for (const [action, expectedAction] of expected) {
  console.log(`${action}@${expectedAction.version} -> ${expectedAction.sha}`)
}
