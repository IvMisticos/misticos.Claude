import type { Plugin } from "@opencode-ai/plugin"
import { readFileSync, realpathSync } from "node:fs"
import { dirname, join } from "node:path"

const rulesPath = join(dirname(dirname(realpathSync(import.meta.path))), "CLAUDE.md")

export const MisticosRules: Plugin = async () => ({
  "experimental.chat.system.transform": async (_input, output) => {
    output.system.push(readFileSync(rulesPath, "utf8"))
  },
})
