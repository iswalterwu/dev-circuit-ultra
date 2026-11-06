import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'

const SKILL_NAMES = ['dev-circuit-ultra', 'dev-circuit-archivist', 'dev-circuit-ledger']

function readSkill(skillName) {
  const directory = fileURLToPath(new URL(`./skills/${skillName}/`, import.meta.url))
  const raw = readFileSync(join(directory, 'SKILL.md'), 'utf8')
  const match = raw.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?/)
  if (!match) throw new Error(`${skillName}/SKILL.md has no frontmatter`)

  const fields = {}
  for (const line of match[1].split(/\r?\n/)) {
    const field = line.match(/^([A-Za-z][A-Za-z0-9_-]*):\s*(.*)$/)
    if (field) fields[field[1]] = field[2].trim().replace(/^(["'])(.*)\1$/, '$2')
  }
  if (!fields.name || !fields.description) {
    throw new Error(`${skillName}/SKILL.md requires name and description`)
  }

  return {
    name: fields.name,
    description: fields.description,
    ...(fields.whenToUse ? { whenToUse: fields.whenToUse } : {}),
    content: raw.slice(match[0].length),
    source: 'bundled',
    resourceBase: { kind: 'directory', path: directory },
    ...(fields['disable-model-invocation'] === 'true'
      ? { invocation: { modelInvocable: false, userInvocable: true } }
      : {}),
  }
}

export const name = 'dev-circuit-ultra'
export const inject = ['skills']

export function apply(ctx) {
  for (const skillName of SKILL_NAMES) {
    ctx.skills.register(readSkill(skillName))
  }
}
