# House rules for agents in this repo

- Never modify anything under `tests/` or `constitution.md`. These are the target,
  not something you may change.
- Implement against the specification you are given; make the existing tests pass.
- Prefer fixed-point `Decimal` for money. Validate external input. Fail closed.
- Output exactly the JSON contract you are asked for, with no markdown fences.
