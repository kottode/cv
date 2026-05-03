# Architecture

This codebase moving from monolith to layered CLI architecture.

Goal: make system easy to reason about, safe to change, fast to extend.

## Core Ideas

- Public command interface stays stable.
- Internal logic split by responsibility, not by random file size.
- Features call internal Python APIs directly.
- No feature calls public CLI through subprocess.
- Migration happens in small verified slices.

## Layer Model

1. Entry layer.

- Thin process bootstrap.
- Only parse argv and forward.

1. Routing layer.

- Single command router.
- Maps command token to feature handler.
- Keeps command surface discoverable in one place.

1. Feature layer.

- Owns command behavior and feature orchestration.
- Exposes command handler plus reusable feature API.
- Uses shared/core helpers and internal facades.

1. Internal integration layer.

- Wraps external systems (network APIs, browser automation, LLM, scraping).
- Keeps external failures and payload quirks isolated.
- Gives stable callable interfaces to features.

1. Shared core layer.

- Shared config/constants/models.
- Shared state/env/file helpers.
- Shared error and utility functions.

## Contracts That Matter

- Command handler contract:

`def cmd_x(args: list[str]) -> int`

- Internal facade contract:

Input/output shaped as plain Python types.
No CLI strings as transport.

- Error contract:

Use one project error type for user-facing failures.
Return codes and stderr remain predictable.

## Dependency Rules

Allowed direction:

- entry -> router -> features -> internal/shared

Avoid:

- internal -> features
- feature -> router
- feature -> public CLI subprocess
- circular imports between features

## Config Strategy

Configuration constants and runtime knobs live in shared config module.

Shared core modules now include config, errors, and utils layers.

Why:

- One source of truth.
- Removes duplicated literals.
- Safer refactor and tooling support.

## Step-by-Step Migration Playbook

1. Pick small command group.
1. Move command logic into feature module.
1. Keep old behavior exact.
1. Extract low-level calls into internal/shared modules only when needed.
1. Wire router to new feature handler.
1. Compile + smoke test command paths.
1. Repeat next command group.

## Build-On-Top Guide

When adding capability:

1. Define command UX first.
1. Add router mapping.
1. Implement feature orchestration in feature module.
1. Add/update internal facade if external dependency involved.
1. Add/update shared config/constants if new knobs needed.
1. Add smoke test path and docs.

When refactoring existing feature:

1. Keep handler signature stable.
1. Move only one concern per patch.
1. Keep outputs and error text stable unless intentionally changing UX.
1. Re-run compile and smoke tests before next slice.

## Verification Gate

Minimum gate per migration slice:

- `python3 -m py_compile` for touched modules.
- `cv help` runs.
- Touched command family smoke-tests pass.
- Install flow still copies all runtime files.
