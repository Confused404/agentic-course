# Appendix (dated 2026-11-04)

- **Docker flags used** (`DockerSandbox.command_line`): `--network none --memory 1g --cpus 1 --pids-limit 256
  --cap-drop ALL --security-opt no-new-privileges --user <uid>:<gid>`. All long-standing Docker flags. On macOS,
  Docker Desktop, OrbStack and Colima all support them. Rootless Docker/Podman add another layer.
- **Stronger isolation options** (not used in the course): gVisor (`--runtime=runsc`), Kata Containers, Firecracker
  microVMs, and hosted sandboxes from several vendors. Same interface (run a command, get output), stronger boundary.
- **Production coding agents' permission models** change often. As of this date, Claude Code has permission
  modes (including an "auto" mode that uses a classifier for actions outside a safe allow-list; see Anthropic's
  engineering post "How we built Claude Code auto mode"), project-level allow/deny rules in `.claude/settings.json`,
  and hooks that can veto tool calls. OpenCode has an `opencode.json` `permission` section (allow/ask/deny for edit and
  bash). Check each tool's docs for current syntax. The concepts in TEXTBOOK §5 map directly.
- **`str_replace`-style editing** is the convention in Anthropic's text-editor tool and in most open-source coding
  agents as of this date. Some agents add a "patch" tool for multi-file changes.
