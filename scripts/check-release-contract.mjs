import { existsSync, lstatSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('..', import.meta.url))
const rootPackage = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'))
const violations = []

function requireFile(path, label) {
  const absolute = join(root, path)
  if (!existsSync(absolute) || !lstatSync(absolute).isFile()) {
    violations.push(`${label} missing: ${path}`)
  }
}

const expected = {
  name: 'dhs-multi-agent',
  main: './dist/index.js',
  types: './dist/types/index.d.ts',
  exportImport: './dist/index.js',
  exportTypes: './dist/types/index.d.ts',
  patch: './cordis.patch.yml',
}

if (rootPackage.name !== expected.name) violations.push(`package name must be ${expected.name} (got ${String(rootPackage.name)})`)
if (rootPackage.private === true) violations.push('package must be publishable; private=true is forbidden')
if (rootPackage.license !== 'MIT') violations.push(`license must be MIT (got ${String(rootPackage.license)})`)
if (rootPackage.main !== expected.main) violations.push(`main must be ${expected.main} (got ${String(rootPackage.main)})`)
if (rootPackage.types !== expected.types) violations.push(`types must be ${expected.types} (got ${String(rootPackage.types)})`)
if (rootPackage.exports?.['.']?.import !== expected.exportImport) violations.push(`exports[.].import must be ${expected.exportImport}`)
if (rootPackage.exports?.['.']?.types !== expected.exportTypes) violations.push(`exports[.].types must be ${expected.exportTypes}`)
if (rootPackage.publishConfig?.access !== 'public') violations.push('publishConfig.access must be public')
if (rootPackage.dsh?.bundle?.patch !== expected.patch) violations.push(`dsh.bundle.patch must be ${expected.patch}`)
if (!Array.isArray(rootPackage.files) || !rootPackage.files.includes('dist')) violations.push('files must include dist')
if (!Array.isArray(rootPackage.files) || !rootPackage.files.includes('cordis.patch.yml')) violations.push('files must include cordis.patch.yml')
if (!String(rootPackage.engines?.node ?? '').includes('22.14.0')) violations.push('engines.node must retain the supported Node 22.14.0 baseline')
if (String(rootPackage.dependencies?.['@deepseek-ai/dsh-agent'] ?? '').startsWith('workspace:')) violations.push('runtime dependency @deepseek-ai/dsh-agent cannot use workspace: protocol')
if (String(rootPackage.dependencies?.['@deepseek-ai/dsh-llm'] ?? '').startsWith('workspace:')) violations.push('runtime dependency @deepseek-ai/dsh-llm cannot use workspace: protocol')
if (String(rootPackage.dependencies?.['@deepseek-ai/dsh-session'] ?? '').startsWith('workspace:')) violations.push('runtime dependency @deepseek-ai/dsh-session cannot use workspace: protocol')

requireFile('dist/index.js', 'release entry')
requireFile('dist/types/index.d.ts', 'type declaration entry')
requireFile('cordis.patch.yml', 'DSH bundle patch')

const forbiddenScripts = ['file:', 'link:', 'workspace:']
for (const [name, value] of Object.entries(rootPackage.scripts ?? {})) {
  const script = String(value)
  if (forbiddenScripts.some(token => script.includes(token))) {
    violations.push(`script ${name} contains a non-publishable dependency reference`)
  }
}

if (violations.length > 0) {
  console.error('Native release contract failed:')
  for (const violation of violations) console.error(`- ${violation}`)
  process.exit(1)
}

console.log(`Native release contract passed for ${rootPackage.name}@${rootPackage.version}.`)
console.log(`Entry: ${rootPackage.main}`)
console.log(`Types: ${rootPackage.types}`)
console.log(`DSH patch: ${rootPackage.dsh.bundle.patch}`)
console.log(`Publish access: ${rootPackage.publishConfig.access}`)
