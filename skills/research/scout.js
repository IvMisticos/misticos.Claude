export const meta = {
  name: 'research-scouts',
  description: 'Run one misticos:scout per research angle, and stop starting scouts once one reaches the web search limit',
  phases: [{ title: 'Scout' }],
}

const SCOUTS_AT_ONCE = 8

const FINDINGS_SCHEMA = {
  type: 'object',
  properties: {
    facts: {
      type: 'array',
      items: {
        type: 'object',
        properties: { fact: { type: 'string' }, url: { type: 'string' } },
        required: ['fact', 'url'],
      },
    },
    numbers: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          number: { type: 'string' },
          meaning: { type: 'string' },
          year: { type: 'string' },
          url: { type: 'string' },
        },
        required: ['number', 'meaning', 'url'],
      },
    },
    quotes: {
      type: 'array',
      items: {
        type: 'object',
        properties: { quote: { type: 'string' }, speaker: { type: 'string' }, url: { type: 'string' } },
        required: ['quote', 'speaker', 'url'],
      },
    },
    notFound: { type: 'array', items: { type: 'string' } },
    reachedSearchLimit: { type: 'boolean' },
  },
  required: ['facts', 'numbers', 'quotes', 'notFound', 'reachedSearchLimit'],
}

function isAngle(angle) {
  return typeof angle?.name === 'string'
    && typeof angle.question === 'string'
    && (angle.known === undefined || Array.isArray(angle.known))
}

function hasUniqueNames(angles) {
  return new Set(angles.map(angle => angle.name)).size === angles.length
}

function parseResearch(input) {
  const trust = input?.trust ?? []
  const avoid = input?.avoid ?? []
  if (typeof input?.goal !== 'string' || !Array.isArray(trust) || !Array.isArray(avoid)) {
    throw new Error('args needs goal: string, and optional trust and avoid lists')
  }
  if (!Array.isArray(input.angles) || !input.angles.every(isAngle) || !hasUniqueNames(input.angles)) {
    throw new Error('args needs angles: [{ name, question, known? }] with unique names')
  }
  return {
    goal: input.goal,
    scope: input.scope ?? 'Any period, place, group, and language.',
    trust,
    avoid,
    angles: input.angles,
  }
}

function briefFor(angle, research) {
  return [
    `Answer this question from public web sources: ${angle.question}`,
    `The goal of the research: ${research.goal}`,
    `Scope: ${research.scope}`,
    `Sources to prefer: ${research.trust.join('; ') || 'none named'}.`,
    `Sources to avoid: ${research.avoid.join('; ') || 'none named'}.`,
    `Already found, so search past these: ${angle.known?.join('; ') || 'nothing yet'}.`,
    'Search in any language the scope allows. Write the findings in English, and keep quotes in their original language.',
    'If a search fails because of the web search limit, even your first one, stop searching, set reachedSearchLimit, and return what you have.',
  ].join('\n\n')
}

const research = parseResearch(args)
const findingsByAngle = {}
const limitedAngles = new Set()
const failedAngles = new Set()
let searchLimitReached = false
let nextAngleIndex = 0

async function scout(angle) {
  try {
    return await agent(briefFor(angle, research), {
      label: angle.name,
      phase: 'Scout',
      agentType: 'misticos:scout',
      schema: FINDINGS_SCHEMA,
    })
  } catch (error) {
    log(`${angle.name} failed: ${error.message}`)
    return null
  }
}

async function scoutNextAngles() {
  while (nextAngleIndex < research.angles.length) {
    const angle = research.angles[nextAngleIndex++]
    if (searchLimitReached) {
      limitedAngles.add(angle)
      continue
    }
    const findings = await scout(angle)
    if (!findings) {
      failedAngles.add(angle)
      continue
    }
    findingsByAngle[angle.name] = findings
    if (findings.reachedSearchLimit) {
      searchLimitReached = true
      limitedAngles.add(angle)
    }
  }
}

await parallel(Array.from({ length: SCOUTS_AT_ONCE }, () => scoutNextAngles))

function inAngleOrder(angles) {
  return research.angles.filter(angle => angles.has(angle))
}

if (limitedAngles.size) {
  log(`${limitedAngles.size} angles reached the search limit. Run them again in a later turn.`)
}
if (failedAngles.size) {
  log(`${failedAngles.size} angles failed.`)
}

return { findingsByAngle, limitedAngles: inAngleOrder(limitedAngles), failedAngles: inAngleOrder(failedAngles) }
