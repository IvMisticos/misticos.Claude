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

function parseResearch(input) {
  const trust = input?.trust ?? []
  const avoid = input?.avoid ?? []
  if (typeof input?.goal !== 'string' || !Array.isArray(input.angles) || !Array.isArray(trust) || !Array.isArray(avoid)) {
    throw new Error('args needs goal: string, angles: [{ name, question }], and optional trust and avoid lists')
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
    'Write the findings in English.',
    'If you reach the web search limit, stop searching, set reachedSearchLimit, and return what you have.',
  ].join('\n\n')
}

const research = parseResearch(args)
const findingsByAngle = {}
const unfinishedAngles = new Set()
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
      unfinishedAngles.add(angle)
      continue
    }
    const findings = await scout(angle)
    if (!findings) {
      unfinishedAngles.add(angle)
      continue
    }
    findingsByAngle[angle.name] = findings
    if (findings.reachedSearchLimit) {
      searchLimitReached = true
      unfinishedAngles.add(angle)
    }
  }
}

await parallel(Array.from({ length: SCOUTS_AT_ONCE }, () => scoutNextAngles))

const unfinishedInOrder = research.angles.filter(angle => unfinishedAngles.has(angle))
if (unfinishedInOrder.length) {
  log(`${unfinishedInOrder.length} angles are unfinished. Run them again in a later turn.`)
}

return { findingsByAngle, unfinishedAngles: unfinishedInOrder }
