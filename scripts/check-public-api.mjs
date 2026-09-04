import { pathToFileURL } from 'node:url'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { readFile } from 'node:fs/promises'

const root = fileURLToPath(new URL('..', import.meta.url))
const packageJson = JSON.parse(await readFile(join(root, 'package.json'), 'utf8'))
const entry = join(root, packageJson.main)
const module = await import(pathToFileURL(entry).href)

const requiredExports = [
  'apply',
  'AgentRunner',
  'Scheduler',
  'runDag',
  'createSupervisor',
  'createRecoveryManager',
  'RuntimeDiagnostics',
  'RunRegistry',
  'createRuntimeDiagnostics',
]

const missing = requiredExports.filter(name => !(name in module))
if (missing.length > 0) {
  console.error('Native public API guard failed:')
  for (const name of missing) console.error(`- missing public export: ${name}`)
  process.exit(1)
}

console.log(`Native public API guard passed for ${packageJson.name}@${packageJson.version}.`)
console.log(`Entry: ${packageJson.main}`)
console.log(`Verified exports: ${requiredExports.join(', ')}`)
