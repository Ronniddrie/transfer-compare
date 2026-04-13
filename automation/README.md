# Bank Transactions Automation

Automates Halifax → `Banking Transactions Live.xlsm` so new transactions land in the workbook without any manual step. Manual CSV download is preserved as a fallback.

See:
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — design, layers, non-goals, cost
- [`docs/SETUP.md`](docs/SETUP.md) — step-by-step setup for the Mac Mini
- [`docs/NEXT_STEPS.md`](docs/NEXT_STEPS.md) — what you can do right now vs what needs the Mac Mini

## Status

- 2026-04-11 — Architecture agreed, project scaffolded in hotel. Waiting on Enable Banking signup (Phase 1 of SETUP.md) before `fetch_halifax.py` can be written.
