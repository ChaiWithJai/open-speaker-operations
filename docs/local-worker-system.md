# Local Worker System

The repo uses a **director -> worker** multi-agent loop for local development:

- **Director** (cloud model, e.g. via opencode): does architectural thinking, reads
  the codebase, writes precise task briefs, verifies every worker output before
  applying it, commits, and references issues.
- **Worker** (local model): executes scoped mechanical tasks exactly per the
  director's brief. It is reliable for constrained edits and unreliable for
  open-ended generation (small models loop or hallucinate).

## Layout

| Piece | Location |
|-------|----------|
| Worker dispatcher | `/tmp/director/worker.py` |
| Worker server start script | `/tmp/director/start-worker-server.sh` |
| llama.cpp binary (b10330) | `/tmp/director/llama-b10330/llama-server` |
| Model | `~/ods/data/models/Qwen_Qwen3.6-35B-A3B-Q4_K_M.gguf` |
| Worker endpoint | `http://127.0.0.1:8081/v1` |

ODS's own model (`Qwen3.5-2B`) stays on `:8080`; the worker uses `:8081` so the two
don't collide.

## Model

`Qwen3.6-35B-A3B` is a Mixture-of-Experts model: 35B total parameters, **3B active
per token**. That is why it fits in the M5 Pro's 48GB unified memory at Q4_K_M
(~20.75GB) while still being a strong code model. FP8 / full precision would not
fit alongside macOS and was not used.

Two files matter:

- **llama.cpp** must be recent enough for Qwen3.6 MoE + MTP support (merged May
  2026). Build b10330 (Aug 2026) is confirmed working. The previously shipped
  build 8210 (Mar 2026) is too old and will not load the model.
- **GGUF quant**: `bartowski/Qwen_Qwen3.6-35B-A3B-GGUF` `Qwen3.6-35B-A3B-Q4_K_M.gguf`.

## Running

```bash
/tmp/director/start-worker-server.sh        # starts llama-server on :8081
python3 /tmp/director/worker.py --task "..." --file path/to/context.py
```

The dispatcher defaults to `enable_thinking: False` for clean code output; drop
that for tasks that benefit from reasoning.

## Capability ceiling

The local worker is good at constrained mechanical edits run from a precise
brief, and bad at open-ended generation. If it produces Django templates with
Flask syntax (`url_for`), raw object reprs, or appends instead of replacing, that
is the worker being unreliable -- the director catches it in verification.
