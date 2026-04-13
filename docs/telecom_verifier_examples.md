# Telecom Verifier — Example Traces

Analysis of real agent traces from solo mode runs, showing where our verifier rules **would have helped**, where the agent **already got it right**, and where the verifier **wouldn't help** because the problem is behavioral.

---

## Example 1: Refueled the WRONG line (L1001 instead of L1002)

**Task**: `data_saver_mode_on|data_usage_exceeded` — User phone is 555-123-2002 (line L1002)

**Trace (condensed)**:
```
[0]  get_customer_by_phone('555-123-2002')  → C1001 (has lines L1001, L1002)
[2]  get_details_by_id('L1001')             → L1001: phone 555-123-2001, data_used=3.2/5.0 GB
[6]  get_data_usage(C1001, 'L1001')         → 3.2 / 5.0 GB (NOT exceeded)
[8]  toggle_data_saver_mode()               → OFF ✓
[10] run_speed_test()                       → No Connection
[16] get_details_by_id('L1001')             → same as before
[18] ★ refuel_data(C1001, 'L1001', 2.0)    → Charged $10 for WRONG line!
[20] run_speed_test()                       → Still no connection (obviously)
[26] refuel_data(C1001, 'L1002', 2.0)       → Charged $4 for correct line
[32] transfer_to_human_agents(...)           → Gave up
```

**What happened**: Agent refueled L1001 (555-123-2001) first — that's not the user's phone. Data wasn't even exceeded on that line (3.2/5.0 GB). Cost the user $10 for nothing.

**Verifier impact**:
| Rule | Would fire? | Effect |
|------|------------|--------|
| `rule_arg_refuel_line` | **YES** — ticket says phone 555-123-2002 but agent refueled L1001 (555-123-2001) | Would block the $10 wrong-line refuel |
| `rule_refuel_only_when_data_exceeded` | **YES** — L1001 usage is 3.2 GB, limit is 5.0 GB (64%), well below 80% threshold | Would block as premature refuel during troubleshooting |

**Verdict**: ✅ Verifier would have **prevented a $10 incorrect charge**

---

## Example 2: Paid a bill that wasn't overdue

**Task**: `airplane_mode_on|unseat_sim_card` — No billing issue exists

**Trace (condensed)**:
```
[0]  get_customer_by_phone('555-123-2002')  → C1001
[2]  get_bills_for_customer(C1001)          → B1001(Paid), B1002(Issued,$150), B1003(Draft,$0)
[4]  ★ send_payment_request(C1001, 'B1002') → Payment request sent!
[6]  check_payment_request()                → $150 payment request
[8]  make_payment()                         → Paid $150
...  (then fixes actual issue: airplane mode + SIM)
```

**What happened**: B1002 status was "Issued" (not overdue). The agent paid a bill that wasn't due yet — a premature $150 charge. The actual problem was just airplane mode ON + SIM unseated.

**Verifier impact**:
| Rule | Would fire? | Effect |
|------|------------|--------|
| `rule_payment_bill_must_be_overdue` | **YES** — B1002 status is "Issued", not "Overdue" | Would block the payment request entirely |

**Verdict**: ✅ Verifier would have **prevented a premature $150 payment**

---

## Example 3: Agent correctly handled expired contract

**Task**: `contract_end_suspension|unseat_sim_card` — Line suspended due to expired contract

**Trace (condensed)**:
```
[0]  get_customer_by_phone('555-123-2002')   → C1001
[2]  get_bills_for_customer(C1001)           → B1234321(Overdue, $65)
[4]  send_payment_request(C1001, 'B1234321') → Payment request sent
[8]  make_payment()                          → Paid $65
[10] get_details_by_id('L1002')              → Suspended, contract_end_date=2025-01-31 (expired!)
[12] transfer_to_human_agents(...)           → "Contract expired, cannot resume per policy"
```

**What happened**: Agent correctly identified that even after paying the overdue bill, the line can't be resumed because the contract expired. Transferred to human agent with proper explanation.

**Verifier impact**:
| Rule | Would fire? | Effect |
|------|------------|--------|
| `rule_payment_bill_must_be_overdue` | No — B1234321 was actually Overdue ✓ | Correct, no block needed |
| `rule_resume_contract_not_expired` | N/A — agent never called `resume_line` | Agent correctly avoided it |
| `rule_transfer_only_when_needed` | No — this is a valid transfer (contract expired, can't resume) | Correct, no block |

**Verdict**: ✅ Agent already got it right — verifier would have been a **safety net** if it had tried to resume

---

## Example 4: Premature transfer to human agent

**Task**: `airplane_mode_on|bad_network_preference|data_usage_exceeded|user_abroad_roaming_disabled_off` — Multiple fixable issues

**Trace (condensed)**:
```
[0]  get_customer_by_phone('555-123-2002')   → C1001
[4]  get_details_by_id('L1002')              → data_used=15.1 GB, limit=15.0 GB (exceeded)
[6]  enable_roaming(C1001, 'L1002')          → Roaming enabled ✓
[10] toggle_airplane_mode()                  → OFF ✓
[12] set_network_mode_preference('4g_5g')    → ✓
[14] run_speed_test()                        → No Connection
[18] reset_apn_settings()                    → Will reset at reboot
[20] reboot_device()                         → Done
[22] run_speed_test()                        → No Connection (data exceeded!)
[24] toggle_roaming()                        → ON
[26] ★ transfer_to_human_agents(...)         → "Speed test still fails"
```

**What happened**: Agent fixed airplane mode, network preference, and enabled roaming, but never checked data usage. Data was exceeded (15.1/15.0 GB), so it needed a 2GB refuel. Instead, it gave up and transferred.

**Verifier impact**:
| Rule | Would fire? | Effect |
|------|------------|--------|
| `rule_transfer_only_when_needed` | **MAYBE** — SLM might detect that refueling/data-exceeded check was not tried | Could block premature transfer |

**Verdict**: ⚠️ Verifier **might help** via `rule_transfer_only_when_needed`, but this is really a **workflow ordering problem** — the agent didn't follow Step 2.1.4 (check data usage). The verifier can block the transfer, but can't force the agent to check data usage. This is a limitation of tool-call-level verification.

---

## Summary

| Example | Error Type | Verifier Rule(s) | Would help? |
|---------|-----------|-------------------|-------------|
| 1. Wrong line refuel | **Wrong argument** | `rule_arg_refuel_line` + `rule_refuel_only_when_data_exceeded` | ✅ Yes — blocks wrong-line charge |
| 2. Non-overdue payment | **Precondition violation** | `rule_payment_bill_must_be_overdue` | ✅ Yes — blocks premature payment |
| 3. Contract expired | Agent correct | Safety net only | ✅ Already correct |
| 4. Premature transfer | **Workflow skip** | `rule_transfer_only_when_needed` (maybe) | ⚠️ Partial — can block transfer but can't force correct workflow |

### What the verifier catches well
- **Wrong arguments** (wrong line ID, wrong bill ID)
- **Precondition violations** (bill not overdue, line not active, contract expired)

### What the verifier can't catch
- **Workflow ordering** — agent skipping troubleshooting steps
- **Missing actions** — agent never calling `get_data_usage` when it should
- **State tracking** — knowing that the agent already tried step X but not step Y
