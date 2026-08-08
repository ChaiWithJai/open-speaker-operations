# Local Worker System (DEPRECATED)

> **Status: deprecated.** This system was built, validated, and then abandoned
> for the HCI pass in favor of direct work by the orchestrating model. Why —
> and what the local worker was actually capable of — is recorded here so the
> next person doesn't have to re-learn it the slow way.

## What it was

A **director -> worker** multi-agent loop:

- **Director** (cloud model, via opencode): architectural thinking, reading the
  codebase, writing precise task briefs, verifying every worker output before
  applying it, commits, issue references.
- **Worker** (local model): executed scoped mechanical tasks from briefs via a
  dispatcher script.

## Layout (still on disk)

| Piece | Location |
|-------|----------|
| Worker dispatcher | `/tmp/director/worker.py` |
| Worker server start script | `/tmp/director/start-worker-server.sh` |
| llama.cpp binary (b10330) | `/tmp/director/llama-b10330/llama-server` |
| Model | `~/ods/data/models/Qwen_Qwen3.6-35B-A3B-Q4_K_M.gguf` |
| Worker endpoint | `http://127.0.0.1:8081/v1` (was running, now stopped) |

ODS's own model (`Qwen3.5-2B`) stays on `:8080`; the worker used `:8081` so the
two didn't collide.

## Two models were tried

### Qwen3.5-2B (the default, loaded by ODS)

**Verdict: not viable as a worker.**

Observed failure modes on constrained mechanical tasks (this is the stuff a
worker *should* be good at):

| Symptom | Example |
|---------|---------|
| Repetition loop on open-ended generation | Asked to list model fields; emitted the same 6 lines ~100 times until max_tokens. temp=0.0 made it deterministic in the wrong way. |
| Over-cautious refusal | `===== FILE: pretalx_speakerops/models.py (NOT FOUND) =====` — the path was relative and the CWD was wrong; instead of saying "path not found, what's the right one?" it refused the whole task. |
| Framework confusion | Produced `url_for('...', event=event.slug)` — Flask syntax — in a Django template task. |
| Append instead of replace | "Rewrite this template" → output the old raw-repr code *plus* new tables, so raw reprs would have survived. |

A 2B model can follow a 1-step instruction ("reply with exactly: pong") but
degrades on anything requiring it to hold the existing code, the spec, and the
output format in context simultaneously. It was never trusted to produce
apply-it-blindly output.

### Qwen3.6-35B-A3B (Q4_K_M, 20.75GB, loaded on :8081)

**Verdict: capable, but not worth the orchestration cost for this workload.**

This is a Mixture-of-Experts model — 35B total parameters, **3B active per
token** — which is why it fits in the M5 Pro's 48GB unified memory at Q4 and
runs at **~62 tok/s on Metal** via llama.cpp b10330 (Aug 2026, includes MTP
support).

Observed capabilities (validated, not claimed):

| Task | Result |
|------|--------|
| Generate a Django template from a precise spec | Correct `{% extends %}`, `{% url %}`, `{% if %}` tags; proper context variable usage; matched existing style |
| Generate typed, documented Python (fibonacci example) | Correct, type-annotated, docstring'd, edge-case handled |
| Rewrite a dashboard template as a KPI card grid | Clean markup, correct Django tags, sensible class names |

It produced **2-3 template snippets** during the HCI pass that were used
(with verification) in the final diff.

## Why it was abandoned

Three costs outweighed the 35B model's output:

### 1. Memory pressure
The 35B Q4 model sits at ~20GB of the M5 Pro's 48GB unified memory. While it ran,
the Docker web stack (Postgres, Redis, web, worker, mock) and macOS were
fighting for the remaining ~28GB. Docker commands (`docker exec`, `docker ps`,
`docker logs`) started **timing out** under that pressure — not because the
model was slow, but because the container runtime was starved. Every
verification step (rebuild container -> wait for seed -> screenshot -> read
text) got slower the longer the model was up.

### 2. Verification was the bottleneck, not generation
The worker's output always had to be verified by the director (reading the
output, checking for Flask syntax / raw reprs / append-vs-replace, then
applying). For template work, the verification + docker-rebuild cycle took
**longer than just writing the template directly.** The worker added a
generation step *in front of* the same verification step, not *instead of* it.

### 3. Docker rebuilds dominate the loop
Every code change required `docker compose build --no-cache web` (full pretalx
pip install, ~3 min) + wait for seed (~30s) + screenshot verification. That's the
critical path regardless of who wrote the code. Whether the worker generated a
snippet or I wrote it directly, the rebuild-verify cycle was identical — so the
worker's contribution was marginal *time* for the same *verification* cost.

## Contribution comparison

| | Local 35B worker | Direct (orchestrator only) |
|---|---|---|
| Template snippets produced | 2-3 (used, verified) | All templates written directly |
| Docker rebuild-verify cycles | Same number (the bottleneck) | Same number |
| Net time added | +model download (~15 min) + orchestration overhead | None |
| Net time saved | ~0 (verification cost unchanged) | Baseline |
| Code quality after verification | Same (everything verified + fixed by director) | Same |

**Bottom line:** for a workload where every output must be verified and the
verification path goes through a slow Docker rebuild, a local worker that
*generates but does not verify* is a net-negative. It added a generation step
in front of an unchanged verification step, while also starving the
verification environment of memory.

The local worker would make sense for a different workload: one where
verification is cheap (e.g. unit-test-backed generation where the model writes
*and* tests its own code) or where the generation is so voluminous that
parallelizing it across local+cloud is worth the coordination. This was not
that workload.

## What stays

- The model file (`~/ods/data/models/Qwen3.6-35B-A3B-Q4_K_M.gguf`, 20.75GB, valid
  GGUF) and llama.cpp b10330 binary are still on disk if you want them later.
- `worker.py` and `start-worker-server.sh` still work: `start-worker-server.sh`
  then `python3 worker.py --task "..." --file context.py`.
- ODS's 2B model on `:8080` is untouched and unrelated.
