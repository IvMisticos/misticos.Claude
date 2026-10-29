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
        required: ['number', 'meaning', 'year', 'url'],
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
  if (typeof input?.goal !== 'string' || !Array.isArray(input.angles)) {
    throw new Error('args needs goal: string and angles: [{ name, question }]')
  }
  return {
    goal: input.goal,
    scope: input.scope ?? 'Any.',
    avoid: input.avoid ?? [],
    angles: input.angles,
  }
}

function briefFor(angle, research) {
  return [
    `Answer this question from public web sources: ${angle.question}`,
    `The goal of the research: ${research.goal}`,
    `Scope: ${research.scope}`,
    `Sources to avoid: ${research.avoid.join('; ') || 'none named'}.`,
    'Search in any language. Write the findings in English.',
    'If you reach the web search limit, stop searching, set reachedSearchLimit, and return what you have.',
  ].join('\n\n')
}

const research = parseResearch(args)
const findingsByAngle = {}
const unfinishedAngles = []
let searchLimitReached = false
let nextAngleIndex = 0

async function scoutNextAngles() {
  while (nextAngleIndex < research.angles.length) {
    const angle = research.angles[nextAngleIndex++]
    if (searchLimitReached) {
      unfinishedAngles.push(angle)
      continue
    }
    const findings = await agent(briefFor(angle, research), {
      label: angle.name,
      phase: 'Scout',
      agentType: 'misticos:scout',
      schema: FINDINGS_SCHEMA,
    })
    if (!findings) {
      unfinishedAngles.push(angle)
      continue
    }
    findingsByAngle[angle.name] = findings
    if (findings.reachedSearchLimit) {
      searchLimitReached = true
      unfinishedAngles.push(angle)
    }
  }
}

await parallel(Array.from({ length: SCOUTS_AT_ONCE }, () => scoutNextAngles))

if (unfinishedAngles.length) {
  log(`${unfinishedAngles.length} angles are unfinished. Run them again in a later Workflow.`)
}

return { findingsByAngle, unfinishedAngles }
