# Installing one Agent Skill and confirming discovery

Install through the path your host supports, then confirm the host lists and runs the skill. This answer is tied to the frozen snapshot of the starter README stored with this investigation (`snapshot-README.md`, recorded 2026-09-07); upstream text may change afterwards. [starter README](https://github.com/qingsongcui/claude-code-skills/blob/main/README.md)

## Install on Claude Code (marketplace)

Add the marketplace, install the starter, and reload plugins:

```text
/plugin marketplace add qingsongcui/claude-code-skills
/plugin install starter@george-onair-skills
/reload-plugins
```

Plugin skills are namespaced, for example /starter:skill-authoring. [starter README](https://github.com/qingsongcui/claude-code-skills/blob/main/README.md)

## Install on plain Agent Skills clients

From a local clone, copy each individual skill directory into the host's skills directory — do not copy the enclosing `skills/` directory as one nested skill. For example:

```bash
mkdir -p "$HOME/.agents/skills"
cp -R plugins/starter/skills/skill-authoring "$HOME/.agents/skills/"
```

Claude Code without the marketplace uses `~/.claude/skills/` instead. [starter README](https://github.com/qingsongcui/claude-code-skills/blob/main/README.md)

## Verify the host discovered it

Ask the agent to list matching skills, invoke one explicitly, and run the preflight to a JSON verdict. A copied folder alone is not proof that a host discovered it. [starter README](https://github.com/qingsongcui/claude-code-skills/blob/main/README.md)

Host discovery varies by runtime: Cursor and OpenCode paths differ by host version, so confirm discovery in your own host before relying on auto-invocation. This write-up covers the starter repository only and does not claim universal agent-runtime support. [starter README](https://github.com/qingsongcui/claude-code-skills/blob/main/README.md)
