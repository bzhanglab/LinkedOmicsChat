import type { ChatMessage, ToolCallRecord } from "./api"

/** The current tools, keyed by tool ID, as returned by GET /api/v1/tools/. */
export type CurrentTools = Record<string, { inputSchema?: { properties?: Record<string, unknown>; required?: string[] } }>

/** Why a call from the chat can't be repeated today, or null when it can. */
function whyNotRepeatable(call: ToolCallRecord, currentTools?: CurrentTools): string | null {
    if (call.status === "error" || call.status === "missing") {
        return `${call.tool_id} did not run successfully in the chat.`
    }
    if (!currentTools) return null
    const tool = currentTools[call.tool_id]
    if (!tool) {
        return `${call.tool_id} is no longer available; the tools have changed since this chat.`
    }
    const properties = tool.inputSchema?.properties ?? {}
    const argNames = Object.keys(call.arguments ?? {})
    const required = tool.inputSchema?.required ?? []
    if (argNames.some((name) => !(name in properties)) || required.some((name) => !argNames.includes(name))) {
        return `${call.tool_id} now takes different inputs from the ones used in this chat.`
    }
    return null
}

/** Format a JSON value as a Python literal. */
function toPython(value: unknown): string {
    if (value === null || value === undefined) return "None"
    if (value === true) return "True"
    if (value === false) return "False"
    if (typeof value === "number") return String(value)
    if (typeof value === "string") return JSON.stringify(value)
    if (Array.isArray(value)) return `[${value.map(toPython).join(", ")}]`
    if (typeof value === "object") {
        return `{${Object.entries(value as Record<string, unknown>).map(([k, v]) => `${JSON.stringify(k)}: ${toPython(v)}`).join(", ")}}`
    }
    return JSON.stringify(String(value))
}

function questionComment(question: string, index: number): string {
    const oneLine = question.replace(/\s+/g, " ").trim()
    const shortened = oneLine.length > 100 ? `${oneLine.slice(0, 99)}…` : oneLine
    return `# Question ${index}: ${shortened}`
}

/**
 * Build a Python script that repeats every tool call in a chat, with the same inputs,
 * through the public tool API (POST /api/v1/tools/execute). Calls that failed or were
 * blocked in the chat, or that no longer match a current tool, are listed as comments
 * instead of being repeated. Without currentTools, only the chat's own status is checked.
 */
export function buildPythonScript(messages: ChatMessage[], toolApiUrl: string, exportedAt: Date, currentTools?: CurrentTools): string {
    const exportDate = exportedAt.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })
    const body: string[] = []
    const variableCounts: Record<string, number> = {}
    const variables: string[] = []
    let question = ""
    let questionIndex = 0

    for (const msg of messages) {
        if (msg.role === "user") {
            question = msg.content
            continue
        }
        if (msg.role !== "assistant" || !msg.toolCalls?.length) continue

        questionIndex += 1
        body.push("", questionComment(question, questionIndex))
        // An answer can repeat a call exactly (e.g. an ID converted up front, then again by the model)
        const seenInAnswer = new Set<string>()
        for (const call of msg.toolCalls) {
            const callKey = JSON.stringify([call.tool_id, call.arguments])
            if (seenInAnswer.has(callKey)) continue
            seenInAnswer.add(callKey)
            const reason = whyNotRepeatable(call, currentTools)
            if (reason) {
                body.push(`# Not repeated: ${reason}`)
                continue
            }
            const toolName = call.tool_id.split("::").pop() || call.tool_id
            variableCounts[toolName] = (variableCounts[toolName] ?? 0) + 1
            const variable = variableCounts[toolName] === 1 ? toolName : `${toolName}_${variableCounts[toolName]}`
            variables.push(variable)

            const args = [JSON.stringify(call.tool_id), ...Object.entries(call.arguments ?? {}).map(([k, v]) => `${k}=${toPython(v)}`)]
            const oneLine = `${variable} = run(${args.join(", ")})`
            body.push(oneLine.length <= 100 ? oneLine : `${variable} = run(\n${args.map((a) => `    ${a},`).join("\n")}\n)`)
        }
    }

    const analyses = variables.length === 1 ? "1 analysis" : `${variables.length} analyses`
    const footer = variables.length
        ? `\nprint("Finished ${analyses}. Each result is in the variable named after its tool:")\nprint(${JSON.stringify(variables.join(", "))})`
        : "\n# This chat ran no analyses that can be repeated."

    return `# Re-runs the analyses from a LinkedOmicsChat chat, exported ${exportDate}.
# Each run() call repeats one tool call from the chat with the same inputs, through the
# LinkedOmicsChat tool API. The data may have been updated since, so results can differ.
# The API accepts a limited number of tool runs per hour from one address.
#
# Needs the requests package (pip install requests). Run it with python -i to explore
# the results afterwards, or paste it into a notebook.

import requests

API_URL = ${JSON.stringify(toolApiUrl)}


def run(tool_id, **arguments):
    """Run one LinkedOmicsChat tool and return its result."""
    response = requests.post(API_URL, json={"tool_id": tool_id, "arguments": arguments}, timeout=300)
    response.raise_for_status()
    body = response.json()
    if not body.get("success"):
        raise RuntimeError(f"{tool_id} failed: {body.get('error')}")
    return body["result"]

${body.join("\n")}
${footer}
`
}
