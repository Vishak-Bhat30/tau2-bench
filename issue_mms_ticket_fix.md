## [Telecom] MMS ticket text missing data refuel hint for solo mode

### Problem

In the telecom domain, there is an inconsistency between `task_instructions` (what the simulated user knows) and `ticket` (what the agent sees in solo mode) for MMS issue tasks.

**`task_instructions`** tells the user simulator:
> *"You are willing to refuel 2.0 GB of data if necessary, but you do not want to change your mobile data plan."*

**`ticket`** (which the agent reads in solo mode) says only:
> *"They will consider the issue resolved when an MMS message can be successfully sent."*

There is no mention of the customer's willingness to refuel data. In solo mode, the agent has no way to discover this information since there is no interactive user to ask — it only has the ticket. As a result, the agent either:

1. Skips the refuel step entirely, or
2. Refuels the wrong amount (e.g., 0.1 GB instead of 2.0 GB)

This causes a significant number of MMS tasks to fail the `assert_data_refueling_amount` environment assertion, which expects `original_data + 2.0 GB`.

> **Note:** This information *is* present in `mobile_data_issues` tickets but is missing from `mms_issues` tickets.

### Impact

In experiments with Qwen3-30B in solo mode, adding the refuel hint to the ticket text:
- Improved **ENV assertion pass rate** from 72.3% → 78.2% (+17 MMS tasks flipped from fail to pass)
- Improved **overall task pass rate** from 54.4% → 61.4%

### Fix

Add the refuel willingness to the `ticket` field in `src/tau2/domains/telecom/tasks/mms_issues.py`:

```diff
- ticket="...They will consider the issue resolved when an MMS message can be successfully sent.",
+ ticket="...They will consider the issue resolved when an MMS message can be successfully sent. They will not change their mobile data plan but they will refuel 2.0 GB of data if necessary.",
```

Since `tasks.json` is a pre-generated static file, it also needs to be regenerated after this change for the fix to take effect at runtime.
