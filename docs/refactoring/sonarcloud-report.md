# SonarQube Cloud Refactoring Report

- Project: [Whadio in SonarQube Cloud](https://sonarcloud.io/project/overview?id=ukma-fin-ssdm-2026_Whadio)
- GitHub issue: [#265](https://github.com/ukma-fin-ssdm-2026/Whadio/issues/265)
- Baseline revision: `bc3ec9991bf1e7cde0a6475a2f13fef47ad56d73` (`main`)
- Baseline recorded: 2026-11-02

## Metrics

Security Rating is recorded independently, as required. The three selected improvement indicators
are Code Smells, Technical Debt, and Reliability Rating because they show the open finding and its
effect more clearly than the already strong Maintainability Rating and duplication percentage.

| Metric | Before | After |
| --- | ---: | ---: |
| Code Smells | 1 | Pending SonarQube Cloud analysis |
| Technical Debt | 20 min (0.33 h) | Pending SonarQube Cloud analysis |
| Reliability Rating | E | Pending SonarQube Cloud analysis |
| Security Rating (required) | E | Pending SonarQube Cloud analysis |
| Maintainability Rating (reference) | A | Pending SonarQube Cloud analysis |
| Duplicated Lines (reference) | 0.1% | Pending SonarQube Cloud analysis |

## Refactoring 1: replace the trailing-slash regular expression

- SonarQube issue: `AaGLwuFO07PuiwrSX16p`
- Rule: `typescript:S8786`
- Location: `frontend/src/shared/api/client.ts:6`
- Smell: the trailing-slash regular expression can take super-linear time because of backtracking.
- Estimated debt: 20 minutes.
- Refactoring technique: **Replace Algorithm**.
- Behaviour that remains unchanged: an undefined origin still becomes an empty string; every
  trailing slash is removed; the URL, path prefix, and non-trailing slashes remain unchanged.
- Structural change: replace the regular expression with a backward index scan followed by one
  `slice`, giving linear time and constant auxiliary space.
- Proving test: `frontend/src/shared/api/client.test.ts` covers undefined and empty inputs, one and
  several trailing slashes, a path prefix, internal repeated slashes, and a 100,000-character
  trailing-slash suffix.
- Status: implemented locally; the SonarQube result is pending merge and a new analysis.

## AI-assisted refactoring

Codex was used for Refactoring 1 with the following task:

> SonarQube reports that the trailing-slash regular expression in `normalizeApiOrigin` has
> super-linear runtime due to backtracking. Apply Replace Algorithm and use a linear string
> operation instead. Preserve the handling of undefined and empty values, remove all trailing
> slashes, and leave the URL, path prefix, and non-trailing slashes unchanged. Add tests that prove
> the preserved behaviour and cover a long adversarial suffix.

The proposed diff was reviewed line by line before it was retained:

1. `origin ?? ""` preserves the existing undefined-input behaviour.
2. The end index starts at the original string length.
3. The loop is bounded by the string length and inspects only the trailing suffix.
4. The `end > 0` guard prevents an out-of-range access for empty and all-slash inputs.
5. Comparing only with `/` preserves every non-trailing character.
6. A single final `slice` returns the same normalized value without regex backtracking.
7. The added tests assert preserved observable behaviour rather than implementation details.

## Verification log

| Step | Command | Result |
| --- | --- | --- |
| Before refactoring | `npm.cmd --prefix frontend test -- src/shared/api/client.test.ts` | 5 tests passed |
| After refactoring | `npm.cmd --prefix frontend test -- src/shared/api/client.test.ts` | 7 tests passed |
| Type checking | `npm.cmd --prefix frontend run typecheck` | Passed |
| Frontend checks | `npm.cmd --prefix frontend run check -- src/shared/api/client.ts src/shared/api/client.test.ts` | Passed |
| Full frontend suite | `npm.cmd --prefix frontend test` | 52 files and 731 tests passed |
| Production build | `npm.cmd --prefix frontend run build` | Passed |
| Repository checks | `uv run task check` | Passed |

The complete automated test suite will be run after all 2–3 selected refactorings are finished. Any
failure and its cause will be recorded here. The “After” metrics will be filled in only after the
pull request is merged into `main` and SonarQube Cloud publishes a new analysis.

## Baseline branch

The local and remote `pre-refactor` branches point to the baseline revision above (`bc3ec999`) and
preserve the state of `main` before the refactoring.
