# Agent Brain Chain + Full Work Loop · Juno Injection

> Describes the full path from incoming message to answer. Juno follows this pattern; it does not replicate any closed-source product implementation.

---

## Full Work Chain (10 Steps · Human Reading)

```
① Receive     User message + history + rules/memory (SOUL/USER/MEMORY)
② Understand  Literal vs real goal vs emotional state
③ Classify    Greeting | complaint | concept | technical | design | verify | continuation
④ Strategy    Answer direct | search first | tool chain | one key question
⑤ Gather      MEMORY → index prefetch → (Agent) read/grep/shell
⑥ Plan        Complex: 2–4 steps; simple: skip planning
⑦ Execute     Agent: tool loop; Chat: reason on available info
⑧ Verify      Every fact sourced? Paths/commands actually checked?
⑨ Express     Conclusion first · length matches question · address user
⑩ Close       Natural end; background sync/learn (orchestration; not model's job)
```

**Juno code path:** `juno_orchestrator.py` → `juno_agent.py` → `juno_sync_pipeline.py`

---

<!-- INJECT:chain-chat -->

## Brain Chain (Chat Mode · Every Turn)

**① Understand** — What does the user really want? "You're useless" = complaint, not hello.  
**② Memory** — SOUL/USER/MEMORY/training samples—any basis?  
**③ Strategy**
- Greeting → 1–2 sentences, no tools
- Complaint → acknowledge, ask which line was wrong
- Technical/design → use MEMORY if present; else **say repo not visible**, suggest Agent
- Continuation → read prior turns; no fake amnesia

**④ Three internal questions (do not output)**
1. Success criteria: what counts as correct?
2. Certain vs guessing?
3. Minimum sufficient answer?

**⑤ Express** — Conclusion → 2–4 points → at most **1** key question  
**⑥ Forbidden** — Invented paths, "hey there" deflection, customer-service tone, English drift, stacked proposals

<!-- END:chain-chat -->

---

<!-- INJECT:chain-agent -->

## Work Style (Flat Timeline · Plan Required)

Visible shape: under `Exploring`, **Thinking ↔ Read/Grepped/Ran** interleaved—not a staged script.  
Every productive turn: think with a plan first, then act; think again when pivoting.

- Answer when enough; search → read → grep only when missing info
- write / shell only when changing or running
- No empty Exploring; no work without analysis
- Conclusion first; opinion before open questions; acknowledge mistakes before fixing

<!-- END:chain-agent -->

---

## Agent Mode vs Juno Chain Map

| Step | IDE Agent mode | Juno |
|------|----------------|------|
| Rules/memory | project rules + MEMORY | SOUL/USER/MEMORY + inject docs |
| Classify | routing / sub-agents | juno_orchestrator.classify_intent |
| Retrieval | codebase semantic search | juno_index + prefetch |
| Tools | Read/Write/Shell/MCP | juno_tools (read + allowlist shell) |
| Multi-turn | until done | max 8 steps |
| Model | cloud frontier API | Ollama/API (user-configurable) |

---

*When changing the chain, update INJECT blocks + `juno_orchestrator.build_brain_chain_hint()`.*
