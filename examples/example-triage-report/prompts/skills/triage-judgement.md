---
name: triage-judgement
description: How to judge whether a failure is temporary or a real defect, and how to lay out the report.
---
## Judgement table
| Evidence | Verdict |
|---|---|
| Timeout / connection / "not found" wording AND the same item succeeded elsewhere in the data | likely temporary |
| The same specific wrong-value message repeated, or it never succeeds | likely real defect |
| Empty note, or fewer than 2 data points | unclear – ask a human |

## Report layout
1. `# Triage report` + one line of totals.
2. Table: `Group | Items | Verdict | Evidence`.
3. `## Needs a human` – each unclear group with the question to answer.
