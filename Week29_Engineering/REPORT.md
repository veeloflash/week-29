# Enterprise Knowledge Workflow Prototype

## Client requirements and scope

I used a simulated company that needs to check whether an employee can approve an expense under the current policy. I wanted the answer to show the employee’s role, the limit that applies and the expense amount. If the policy changes, a new or resumed run should pick that up. The run also needs to survive a restart while someone is reviewing it.

I built a local browser page and a Python workflow engine. The registry stores the source records, and code follows the evidence and prepares the answer. Publishing saves the final answer in the database.

## Knowledge source inventory

| Document | Source authority | Version | Effective date | Contents |
|---|---|---|---|---|
| employees | HR employee directory | 1 | 2026-01-01 | Role and department |
| expenses | Finance expense ledger | 1 | 2026-01-01 | Amount, currency and category |
| approval-policy | Finance approved policy register | 1 | 2026-01-01 | Manager limit 2,000 EUR |
| approval-policy | Finance approved policy register | 2 | 2026-11-01 | Manager limit 1,000 EUR |

I also save the status, content checksum and time each version was received. The inventory shows which versions are current, superseded, scheduled or withdrawn. If two current sources disagree, the run pauses so someone can fix the knowledge.

## Policy-change investigation

For Employee A and Expense X, the first hop finds that A is a manager. The next hop uses that role to find the 1,000 EUR limit in policy v2. The last hop finds the 1,500 EUR expense and compares it with the limit. The answer says A cannot approve it, with a reference to each hop.

After those three facts, the workflow waits for review. If a source is missing, it pauses for a retry with an attempt limit. If sources conflict, it waits for a correction.

Using v1 here would give the wrong answer because its manager limit was 2,000 EUR. To test rollback, I added an incorrect v3 limit of 9,000 EUR, checked that it changed the result and restored v2. I also kept five regression questions for A/X, A/Y, B/X, B/Z and C/Y.

## Update audit

Old knowledge can enter at several points. The wrong file might be ingested, the effective date might be wrong, an unofficial source might be trusted, a cache might keep old chunks, or a saved fact or approved draft might survive an update.

I validate a version before saving it, and retrieval reads the effective sources directly. Each workflow keeps a snapshot of the source records. If that snapshot changes before resume or review, I clear the old facts, answer and approval and start Hop 1 again. The tests cover updates while waiting, after approval and midway through retrieval.

## Approval and audit policy

This expense example always stops at WAITING_APPROVAL. The reviewer can read the answer, evidence, source versions and trace. They need a reviewer token and a reason to approve, edit or reject. An edit saves both answers. After approval or edit, Resume continues to publication. Rejection finishes the run.

For each audit event I save who acted, when, what happened, the old and new states and the reason. Retrieval events include the fact and its evidence. I also record how long stages took. A checkpoint keeps the question, plan, facts, versions, retries, answer, approval binding and history.

## Threat analysis

| Threat | Backend defense | Verification |
|---|---|---|
| Frontend forces COMPLETE | Fixed transitions and publish guard | Illegal-transition test |
| Saved state changed directly | Signed checkpoint | State-tampering test |
| Source changed outside ingestion | Signed document record | Document-tampering test |
| Old or copied approval | ID, revision and content/snapshot binding | Replay and cross-workflow tests |
| Knowledge changes after approval | Freshness check before continuation | Stale-approved-review test |
| Retrieved text says publish | Structured fields stay data | Injection regression |
| Unauthorized update or review | Token-to-role mapping and method checks | Role tests and browser/API checks |

This local prototype trusts the reviewer and whoever controls the database key and operating system. It checks source-authority names during admin updates. A real deployment would need a reliable way to authenticate document publishers and protect the storage.

## Failure analysis and improvement

The missing-employee example stops at Hop 1 because it cannot find a verified role. It allows two retries, and the third failed attempt enters FAILED. The trace shows that the HR record is missing, so I’d ask for a verified record before trying again.

The conflicting-policy example stops at Hop 2. Two current official sources give different limits for the same role. The policy owner needs to reconcile them. The recovery test updates the conflicting source and checks that retrieval starts again.

During testing I found SQLite connections staying open on Windows. I fixed the connection manager so it closes them after commit or rollback. I also fixed Resume at the review gate so reopening the same checkpoint keeps its revision and the pending review still works.

## Framework reconstruction

I read LangGraph’s interrupt example as a draft, saved checkpoint, review wait, resume and finish. The thread ID finds the saved state and the resume value carries the review decision. The node runs again after the pause, so I’d check that any earlier actions are safe to repeat. States, guards and persistence still apply in plain Python. The framework supplies the interrupt, Command and checkpoint helpers.

Source consulted for the reconstruction — [LangGraph interrupt documentation](https://github.com/langchain-ai/docs/blob/main/src/oss/langgraph/interrupts.mdx).

## Reflection

Each hop uses an earlier result to decide what to retrieve. If the first role is wrong, the later lookup can succeed and still lead to the wrong answer. Keeping each fact and its source helps me find where that happened.

I’d keep the permission checks and numeric comparisons in code. A model could help understand varied questions, but I’d still check the sources and require review where needed. To reduce review fatigue, I’d group related requests and reuse verified checks while keeping approval tied to the actual answer.