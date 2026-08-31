import { readdir, readFile, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'

const root = fileURLToPath(new URL('../dist/types/', import.meta.url))

async function walk(directory) {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name)
    if (entry.isDirectory()) {
      await walk(path)
      continue
    }
    if (!entry.name.endsWith('.d.ts')) continue

    const input = await readFile(path, 'utf8')
    const output = input.replace(
      /((?:from\s+|import\s*\(\s*)["'])(\.\.?\/[^"']+)(["'])/g,
      (match, prefix, specifier, suffix) => {
        if (/\.[a-z0-9]+$/i.test(specifier)) return match
        return `${prefix}${specifier}.js${suffix}`
      },
    )
    if (output !== input) await writeFile(path, output, 'utf8')
  }
}

await walk(root)
console.log('Native declaration imports normalized for NodeNext consumers.')
