# Milestone 1 — environment and local chat runtime

## Scope delivered

- Dependency-free Python model abstraction and streaming Ollama HTTP adapter.
- Local-only endpoint enforcement for Ollama.
- Discovery and health checks for already-installed models.
- Terminal chat with conversation history, streaming, and one-shot mode.
- Three conservative resource-profile preflights. They are safety gates, not performance promises.
- Windows setup script and tests that do not require model downloads.

## Development environment observed (2026-10-13)

The build sandbox is Debian 12, Python 3.11.2, 2 virtual CPUs, 3.8 GiB RAM, no swap,
and approximately 20 GiB free disk. Ollama and llama.cpp are not installed. This is not the
user's target Windows machine, so no target-hardware benchmark is claimed.

## Deliberately not done

No weights were downloaded because model downloads require explicit approval. Consequently the
real local inference smoke test could not run here. Tests exercise the wire adapter against
controlled responses. Agent actions, MCP, browser control, memory, desktop UI, and training belong
to later milestones and are not claimed in this milestone.

## Resource implications

The source and tests are tiny and have no runtime Python dependencies. A 1B–3B quantized model
usually consumes multiple GiB across weights and runtime state; actual use depends on quantization,
context, and backend and must be measured. The safety gate requires 3 GiB *available* RAM for the
lightweight profile, 12 GiB for 12B inference, and 32 GiB for the training profile. These are
conservative configurable-design defaults, not guarantees that every model fitting the gate works.

A machine with 8 GiB total RAM is expected to use Profile A. The default 12B guard will refuse it.
Training a 12B model from scratch is explicitly outside the supported design.
