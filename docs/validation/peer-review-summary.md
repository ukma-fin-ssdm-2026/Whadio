# Quality Analyst summary: review of pun-intended-team's test plan

Quality Analyst: Denys Zabiiaka. Review run by Zlata (Review Manager), posted as [issue #283](https://github.com/ukma-fin-ssdm-2026/pun-intended-team/issues/283) on their `docs/validation/test-plan.md`; their team accepted it.

## Result

Checklist: 0 of 5 criteria met, all five marked blocking (coverage of key paths, acceptance criteria, negative scenarios, traceability, CI executability).

## Main finding

Most of the needed tests already exist in their repository, but the plan does not name them or trace them to requirement IDs (SAFE-001, PERF-001). The gap is in the plan, not in the code.

## Gaps

- Profile editing is in scope but has no test case of its own; only profile creation (TC-12) is planned.
- Underage rejection is missing; only the positive "turns 18" case is planned.
- Matching lacks score maximization, exclusions, ties, deterministic ordering, concurrency and unmatched users.
- Contact reveal covers only the rejection case, not the reveal after both users accept.

## Biggest risk

Their recorded k6 run failed (2 request errors, 30 s maximum latency) and the cause is not investigated, so PERF-001 is still open.

## Strengths

- The plan targets safety-sensitive areas: age validation, matching, contact disclosure, performance.
- Many tests already exist and can be linked to the plan directly.
- Performance goals are measurable, and the failed run is reported rather than hidden.

## What they should fix first

1. Complete the requirement-to-test traceability matrix: test IDs, repository references, owners, execution results.
2. Separate deterministic CI tests from staging-only load tests, with the environment, command and pass/fail threshold for each.
