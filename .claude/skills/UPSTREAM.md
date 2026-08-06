# Vendored: Superpowers

These skills are a verbatim copy of the `skills/` directory from
[obra/superpowers](https://github.com/obra/superpowers), vendored into this
repository so they load as project skills without a plugin install.

| | |
|---|---|
| Upstream | https://github.com/obra/superpowers |
| Version | 6.2.0 |
| Commit | `44c9b2d6e889982ac18c27d05a19fefe335194e1` |
| License | MIT — Copyright (c) 2025 Jesse Vincent (see `LICENSE`) |

## What was changed

Only one thing. Upstream ships a `SessionStart` hook that injects the
`using-superpowers` skill into context at the start of every session, and it
locates the skills via `${CLAUDE_PLUGIN_ROOT}`. Vendored as project skills there
is no plugin root, so `.claude/hooks/superpowers-session-start` resolves the path
relative to itself and always emits Claude Code's `hookSpecificOutput` shape
instead of branching per harness. It is wired up in `.claude/settings.json`.

The skill files themselves are unmodified.

## Updating

```bash
git clone --depth 1 https://github.com/obra/superpowers.git /tmp/superpowers
rm -rf .claude/skills
cp -a /tmp/superpowers/skills .claude/skills
cp -a /tmp/superpowers/LICENSE .claude/skills/LICENSE
# then restore this file and bump the version/commit above
```

Check upstream's `hooks/session-start` for changes when updating — if it grows
new behavior, port it into `.claude/hooks/superpowers-session-start`.
