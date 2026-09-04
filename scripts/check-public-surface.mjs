import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { readFile } from 'node:fs/promises'

const root = fileURLToPath(new URL('..', import.meta.url))
const [readme, packageText] = await Promise.all([
  readFile(join(root, 'README.md'), 'utf8'),
  readFile(join(root, 'package.json'), 'utf8'),
])
const packageJson = JSON.parse(packageText)
const violations = []

const requiredReadmeTokens = [
  '# DHS Multi-Agent Orchestration',
  'npm install dhs-multi-agent',
  'Native DeepSeek Harness (DSH) multi-agent orchestration for Cordis.',
  'packages/dsh-multi-agent/src/',
  'ctx.multiAgent',
  'Node.js `>=22.14.0`',
]

for (const token of requiredReadmeTokens) {
  if (!readme.includes(token)) violations.push(`README is missing required Native product text: ${token}`)
}

const forbiddenReadmeTokens = [
  'https://github.com/Li3NGa/deepseek-multi-agent-plugin/actions/workflows/ci.yml',
  'https://img.shields.io/pypi/v/deepseek-multi-agent-plugin.svg',
]

for (const token of forbiddenReadmeTokens) {
  if (readme.includes(token)) violations.push(`README still contains stale Python-primary reference: ${token}`)
}

if (packageJson.name !== 'dhs-multi-agent') violations.push(`published package name must remain dhs-multi-agent (got ${String(packageJson.name)})`)
if (packageJson.main !== './dist/index.js') violations.push('published package main must remain ./dist/index.js')
if (packageJson.types !== './dist/types/index.d.ts') violations.push('published package types must remain ./dist/types/index.d.ts')
if (packageJson.publishConfig?.access !== 'public') violations.push('published package must remain public')

if (violations.length > 0) {
  console.error('Public product surface check failed:')
  for (const violation of violations) console.error(`- ${violation}`)
  process.exit(1)
}

console.log(`Public product surface check passed for ${packageJson.name}@${packageJson.version}.`)
