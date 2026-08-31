import { readdir, readFile, stat, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const root = fileURLToPath(new URL('../dist/types/', import.meta.url))

async function exists(path) {
  try {
    await stat(path)
    return true
  } catch {
    return false
  }
}

async function normalizeSpecifier(declarationFile, specifier) {
  if (/\.[a-z0-9]+$/i.test(specifier)) return specifier

  const base = dirname(declarationFile)
  const fileTarget = join(base, `${specifier}.d.ts`)
  if (await exists(fileTarget)) return `${specifier}.js`

  const indexTarget = join(base, specifier, 'index.d.ts')
  if (await exists(indexTarget)) return `${specifier}/index.js`

  throw new Error(
    `cannot resolve relative declaration import '${specifier}' from ${declarationFile}`,
  )
}

async function walk(directory) {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name)
    if (entry.isDirectory()) {
      await walk(path)
      continue
    }
    if (!entry.name.endsWith('.d.ts')) continue

    const input = await readFile(path, 'utf8')
    const pattern = /((?:from\s+|import\s*\(\s*)["'])(\.\.?\/[^"']+)(["'])/g
    let output = ''
    let cursor = 0
    let match

    while ((match = pattern.exec(input)) !== null) {
      output += input.slice(cursor, match.index)
      const normalized = await normalizeSpecifier(path, match[2])
      output += `${match[1]}${normalized}${match[3]}`
      cursor = pattern.lastIndex
    }

    output += input.slice(cursor)
    if (output !== input) await writeFile(path, output, 'utf8')
  }
}

await walk(root)
console.log('Native declaration imports normalized for NodeNext consumers.')
