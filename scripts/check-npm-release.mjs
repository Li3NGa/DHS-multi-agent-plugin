import { readFile } from 'node:fs/promises'

const packageJson = JSON.parse(await readFile(new URL('../package.json', import.meta.url), 'utf8'))
const tag = process.argv[2] ?? process.env.GITHUB_REF_NAME

if (!tag) {
  throw new Error('release tag is required (expected npm-vX.Y.Z)')
}

const expected = `npm-v${packageJson.version}`
if (tag !== expected) {
  throw new Error(`npm release tag '${tag}' does not match package version ${packageJson.version}; expected '${expected}'`)
}

console.log(`npm release check passed: ${packageJson.name}@${packageJson.version} <- ${tag}`)
