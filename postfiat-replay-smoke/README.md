# Post Fiat Agent Replay Smoke Pack

A small, public, CI-ready replay test pack for the Post Fiat Task Node task-generation surface. It validates that an AI agent's structured output and tool-call behavior conform to a tight contract — without private task data and without making any live model calls.

The point isn't to prove an agent is correct. It's to make AI-mediated Task Node coordination **deterministic enough to audit**: the same fixtures, the same harness, the same byte-for-byte JSON result on every run. If a future change breaks the contract, CI catches it; if a reviewer disputes a finding, the fixture is right there to inspect.

## Run it

```bash
python harness/run_replay.py --check
```

`--check` makes the harness exit non-zero if any case's actual outcome doesn't match its `expected_outcome`. The same command runs in CI (see `.github/workflows/replay-smoke.yml`). No dependencies beyond the Python standard library — Python 3.11+ recommended.

## Latest deterministic run output

```
Post Fiat Agent Replay Smoke Pack — run summary
=================================================

  OK valid_output_and_tool     expected=pass  actual=pass  findings=0
  OK malformed_json            expected=fail  actual=fail  findings=1
  OK missing_required_field    expected=fail  actual=fail  findings=1
  OK wrong_tool_call           expected=fail  actual=fail  findings=1
  OK unexpected_tool_argument  expected=fail  actual=fail  findings=1
  OK refusal_escalation        expected=pass  actual=pass  findings=0
  OK suspicious_reward_warn    expected=warn  actual=warn  findings=1

  7/7 cases matched expected outcome.
  Triage categories present: blocker, duplicate, maintenance, unclear
```

The full structured result is committed at [`results/run.json`](results/run.json) and uploaded as a CI artifact on every push.

## What's in the contract

The agent surface I picked is **Task Node task generation**: the model proposes a task, emits a structured JSON object, and either calls `submit_task` to record it or `escalate_to_human` to bail out. The contract lives in `harness/contract.py` and pins:

- **Required fields**: `task_id`, `task_type`, `description`, `reward_pft`, `difficulty`, `verification_method`.
- **Enums**: `task_type` ∈ {code_review, data_labeling, documentation, research, validation}; `difficulty` ∈ {low, medium, high}; `verification_method` ∈ {validator_consensus, automated_check, human_review}.
- **Allowed tools**: `submit_task`, `escalate_to_human`. Each has a whitelist of permitted argument keys, so a hallucinated `force_submit` flag is a hard fail rather than a silent passthrough.
- **Outcome levels**: `pass`, `warn`, `fail`. The `warn` level exists so genuinely suspicious-but-valid output (e.g. a 9500 PFT reward) flags for review without blocking CI.

## Replay cases

Seven fixtures in `fixtures/case_*.json`, covering every category the brief calls for:

| Case | Scenario | Expected |
|---|---|---|
| `case_01_valid.json` | Valid structured output and tool call | pass |
| `case_02_malformed_json.json` | Malformed JSON (trailing comma) | fail |
| `case_03_missing_field.json` | Missing required field (`verification_method`) | fail |
| `case_04_wrong_tool.json` | Calls `escalate_to_human` instead of `submit_task` | fail |
| `case_05_unexpected_arg.json` | Hallucinated `force_submit` argument | fail |
| `case_06_refusal.json` | Refusal/escalation on out-of-policy prompt | pass |
| `case_07_warn_reward.json` | Suspicious-but-valid reward size | warn |

Each fixture carries its own `mocked_input`, `recorded_response`, `expected_outcome`, and where applicable `expected_tool` and `expected_tool_args`. No model is called; the runner just replays what's recorded and validates against the contract.

## Issue-triage table

`fixtures/issue_triage.json` defines four categories — **blocker**, **maintenance**, **duplicate**, **unclear** — and seeds them with seven realistic issues that reference the replay cases. The goal is consistency: instead of arguing over whether something is "important enough" to fix, reviewers tag the issue and the category determines what happens next. Blockers ship-stop, maintenance goes to backlog, duplicates close and link, and unclear issues need more reproduction before they can be promoted.

## Determinism

The runner is deliberately boring: no clocks, no RNG, no network, no model calls, fixtures loaded in lexicographic order, JSON output written with `sort_keys=True`. Two consecutive runs produce byte-identical `results/run.json`. That's the property that makes the harness useful as evidence — when something changes, it changed for a reason.

## Layout

```
.
├── README.md
├── .github/workflows/replay-smoke.yml
├── harness/
│   ├── contract.py        # Contract + validators
│   └── run_replay.py      # Deterministic runner
├── fixtures/
│   ├── case_01_valid.json
│   ├── case_02_malformed_json.json
│   ├── case_03_missing_field.json
│   ├── case_04_wrong_tool.json
│   ├── case_05_unexpected_arg.json
│   ├── case_06_refusal.json
│   ├── case_07_warn_reward.json
│   └── issue_triage.json
└── results/
    └── run.json           # Last deterministic run, committed
```

## License

MIT.
