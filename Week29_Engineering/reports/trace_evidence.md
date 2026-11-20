# Workflow trace evidence

## happy_path

Can Employee A approve Expense X under the current policy?

Final state is COMPLETE.

- 2026-11-20T19:51:21.015789+00:00 system NEW → VALIDATING — Validate supported question.
- 2026-11-20T19:51:21.016297+00:00 system VALIDATING → PLANNING — Supported employee/expense question.
- 2026-11-20T19:51:21.016297+00:00 system PLANNING → HOP1 — Three dependent evidence steps planned.
- 2026-11-20T19:51:21.016297+00:00 system HOP1 → HOP1 — HOP1 produced a supported intermediate fact.
- 2026-11-20T19:51:21.016297+00:00 system HOP1 → HOP2 — Evidence recorded.
- 2026-11-20T19:51:21.017834+00:00 system HOP2 → HOP2 — HOP2 produced a supported intermediate fact.
- 2026-11-20T19:51:21.017834+00:00 system HOP2 → HOP3 — Evidence recorded.
- 2026-11-20T19:51:21.017834+00:00 system HOP3 → HOP3 — HOP3 produced a supported intermediate fact.
- 2026-11-20T19:51:21.017834+00:00 system HOP3 → VERIFYING — Evidence recorded.
- 2026-11-20T19:51:21.017834+00:00 system VERIFYING → DRAFTING — All three hops have evidence.
- 2026-11-20T19:51:21.017834+00:00 system DRAFTING → WAITING_APPROVAL — Expense authorization requires human review.
- 2026-11-20T19:51:21.024392+00:00 reviewer-1 WAITING_APPROVAL → WAITING_APPROVAL — Checked HR role, current limit and expense.
- 2026-11-20T19:51:21.024392+00:00 system WAITING_APPROVAL → APPROVED — Checked HR role, current limit and expense.
- 2026-11-20T19:51:21.030480+00:00 system APPROVED → PUBLISHING — Current content-bound approval verified.
- 2026-11-20T19:51:21.030480+00:00 system PUBLISHING → COMPLETE — Publish recorded once in this checkpoint.

## missing_employee

Can Employee Unknown approve Expense X under the current policy?

Final state is FAILED.

- 2026-11-20T19:51:21.039518+00:00 system NEW → VALIDATING — Validate supported question.
- 2026-11-20T19:51:21.039518+00:00 system VALIDATING → PLANNING — Supported employee/expense question.
- 2026-11-20T19:51:21.039518+00:00 system PLANNING → HOP1 — Three dependent evidence steps planned.
- 2026-11-20T19:51:21.039518+00:00 system HOP1 → RETRY_RETRIEVAL — No employees evidence for Employee Unknown.
- 2026-11-20T19:51:21.046893+00:00 system RETRY_RETRIEVAL → HOP1 — Resume bounded retry.
- 2026-11-20T19:51:21.046893+00:00 system HOP1 → RETRY_RETRIEVAL — No employees evidence for Employee Unknown.
- 2026-11-20T19:51:21.052117+00:00 system RETRY_RETRIEVAL → HOP1 — Resume bounded retry.
- 2026-11-20T19:51:21.052117+00:00 system HOP1 → FAILED — No employees evidence for Employee Unknown.

## conflicting_policy

Can Employee A approve Expense X under the current policy?

Final state is CONFLICT.

- 2026-11-20T19:51:21.062450+00:00 system NEW → VALIDATING — Validate supported question.
- 2026-11-20T19:51:21.062450+00:00 system VALIDATING → PLANNING — Supported employee/expense question.
- 2026-11-20T19:51:21.062450+00:00 system PLANNING → HOP1 — Three dependent evidence steps planned.
- 2026-11-20T19:51:21.062450+00:00 system HOP1 → HOP1 — HOP1 produced a supported intermediate fact.
- 2026-11-20T19:51:21.062450+00:00 system HOP1 → HOP2 — Evidence recorded.
- 2026-11-20T19:51:21.062450+00:00 system HOP2 → CONFLICT — Current authoritative policy sources disagree for manager.
