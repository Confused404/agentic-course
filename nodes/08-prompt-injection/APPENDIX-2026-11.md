# Appendix (dated 2026-11): prompt-injection landscape

## Research and guidance worth reading
- Simon Willison, "The lethal trifecta for AI agents" (June 2025) and his prompt-injection series.
- Meta, "Agents Rule of Two: A Practical Approach to AI Agent Security" (Oct 2025).
- Nasr, Carlini, Sitawarin, Schulhoff et al., "The Attacker Moves Second: Stronger Adaptive Attacks Bypass Defenses
  Against LLM Jailbreaks and Prompt Injections" (arXiv 2510.09023; USENIX Security 2026): 12 published defences
  broken by adaptive attacks; human red-teamers succeeded against all of them.
- Beurer-Kellner et al., "Design Patterns for Securing LLM Agents against Prompt Injections" (2025): action selector,
  plan-then-execute, map-reduce, dual LLM, code-then-execute, context minimisation.
- Debenedetti et al. (Google DeepMind), "Defeating Prompt Injections by Design" (CaMeL, 2025): a privileged model
  writes code; an interpreter tracks provenance and enforces capability policies.
- Microsoft, "spotlighting" (delimiting, datamarking, encoding) for indirect prompt injection.
- OWASP Top 10 for LLM Applications: prompt injection is LLM01.

## Benchmarks
AgentDojo (tool-using agents, utility and attack success together), InjecAgent, and vendor red-team reports in model
system cards. Treat published ASRs as static-attack numbers unless the paper says it ran adaptive attacks.

## Vendor features (check current docs)
- Model providers publish prompt-injection results in system cards and train for instruction hierarchy (system >
  developer > user > tool output). Browser and computer-use agents ship with extra classifiers and confirmation
  steps for sensitive actions (Elective E1).
- Guard / classifier models for injection detection exist from several vendors and open-source projects (for
  example Meta's Prompt Guard family). They're filters: measure FPR on your look-alikes and test adaptively.
- MCP clients increasingly show tool descriptions and require approval for new or changed tools: the tool-poisoning
  angle is Node 11.

## Coding agents
Claude Code and OpenCode read files, web pages and command output that may contain injections. Their defences are
the same ones you built: permission prompts for sinks (shell, network, writes), allow/deny rules, sandboxes, and
treating fetched content as data (Node 03, Node 13). The repo you clone is untrusted input.
