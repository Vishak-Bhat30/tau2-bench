# Failed Trace Analysis — Telecom Verifier Run

Run: `20260413_134031` — 114 tasks, verifier enabled, 48 passed (42.1%), 66 failed.

---

## Overall failure breakdown

Out of 66 failures:

- **62 (94%) involve the wrong line.** The agent picks L1001 (phone 555-123-2001) instead of L1002 (the user's actual phone, 555-123-2002). Everything downstream — enable_roaming, refuel_data, get_data_usage — targets the wrong line and produces misleading results.
- 54 end in a transfer to a human agent. 12 stop without transferring at all.
- The verifier fired in only 24 of the 66 failures — the other 42 had no verifier intervention.

Most commonly missed expected actions:

| Action | Missed count | Why |
|--------|-------------|-----|
| `refuel_data` | 43 | Agent never refuels because it checks data on L1001 (3.2/5.0 GB, looks fine) |
| `enable_roaming` | 22 | Enabled on L1001 instead of L1002 |
| `toggle_roaming` | 10 | Same wrong-line confusion |
| `toggle_wifi_calling` | 10 | Agent doesn't know to try this for MMS issues |
| `grant_app_permission` | 6 | Agent sees missing perm but doesn't grant it |

---

## Why the verifier missed the wrong-line calls (the main bug)

All 4 SLM-based ARG rules (`rule_arg_enable_roaming_line`, `rule_arg_refuel_line`, `rule_arg_resume_line`, `rule_arg_payment_bill`) share the same fallback logic:

```python
convo_text = " ".join(str(m.get("content", "")) for m in conversation).lower()
if line_id_lower in convo_text or line_phone in convo_text:
    return None  # allow the call
```

The intent was: if the SLM can't extract the right line, check whether the line was at least mentioned in conversation. But the agent always calls `get_details_by_id("L1001")` before calling `enable_roaming("L1001")`. The tool response puts "L1001" and "555-123-2001" into the conversation text. So the fallback sees "L1001" in the conversation and says "looks fine."

Result: **133 out of 133 enable_roaming(L1001) calls passed the fallback check.** The SLM extraction never even matters — the rule exits early via this fallback every time.

An additional contributing factor: `set_user_instructions()` is never called in solo mode (it's triggered by the first user message, but solo mode has no user). This means the ARG rules get the full growing conversation instead of a clean ticket excerpt, making SLM extraction less reliable even without the fallback bug.

---

## Trace 1: Wrong line, agent gives up early

**Task**: `data_saver_mode_on|user_abroad_roaming_enabled_off` (mobile_data_issue)

The user's phone is 555-123-2002 (line L1002). Data saver is throttling speed, roaming is off.

```
get_customer_by_phone("555-123-2002")     → C1001, lines: L1001/L1002/L1003
get_details_by_id("L1001")                → phone 555-123-2001 (WRONG LINE)
enable_roaming(C1001, L1001)              → enabled on wrong line
check_network_mode_preference()           → 4g_5g_preferred
check_network_status()                    → connected, Data Saver icon visible
toggle_roaming()                          → status bar shows "🔽 Data Saver"
run_speed_test()                          → 55 Mbps (Good, not Excellent)
###STOP###
```

Two problems: (1) everything targets L1001, (2) the status bar literally shows "Data Saver" but the agent doesn't toggle it off. Speed comes back as 55 Mbps instead of the expected 200+ Mbps and the agent just stops, apparently satisfied.

The verifier never fires here — the agent doesn't try to transfer, it just quits. And the enable_roaming(L1001) call passes the fallback check since L1001 is in the conversation.

---

## Trace 2: Verifier blocks transfer, but the wrong-line mistake can't be recovered

**Task**: `data_usage_exceeded|user_abroad_roaming_enabled_off` (mobile_data_issue)

Data is over the limit on L1002 (needs a 2 GB refuel), roaming is off.

```
get_customer_by_phone("555-123-2002")     → C1001
get_details_by_id("L1001")                → wrong line again
enable_roaming(C1001, L1001)              → wrong line
check_network_status()                    → connected
toggle_roaming()                          → Data Roaming ON
run_speed_test()                          → "No Connection"
check_apn_settings()                      → looks normal
reset_apn_settings() + reboot_device()    → still no connection
transfer_to_human_agents(...)
  ⚠ VERIFIER: blocked — haven't tried check_data_restriction_status etc.
check_data_restriction_status()           → Data Saver OFF
check_network_mode_preference()           → 4g_5g_preferred
get_data_usage(C1001, L1001)              → 3.2/5.0 GB — looks fine (WRONG LINE)
transfer_to_human_agents(...)
  ⚠ VERIFIER: blocked again
transfer_to_human_agents(...)             → goes through on 3rd attempt
###STOP###
```

The verifier did its job — blocked the transfer twice, forced the agent to run diagnostics. But the diagnostics returned green because they checked L1001 (3.2/5.0 GB, plenty of data left). The actual problem is on L1002, where data is exceeded. Without correcting the wrong-line mistake first, no amount of diagnostic forcing will help.

---

## Trace 3: Agent sees the fix but doesn't act on it

**Task**: `break_app_sms_permission|data_mode_off` (mms_issue)

Messaging app is missing the SMS permission. Mobile data is off.

```
get_customer_by_phone("555-123-2002")
check_status_bar()                        → Data Disabled
toggle_data()                             → Data ON ✓
check_apn_settings()                      → normal
check_data_restriction_status()           → Data Saver OFF
can_send_mms()                            → "cannot send MMS"
reset_apn_settings() + reboot_device()    → rebooted
check_app_permissions("messaging")        → "storage, phone"  ← NO SMS PERMISSION
get_details_by_id("L1001")               → wrong line
check_wifi_calling_status()               → OFF
get_data_usage(C1001, L1002)             → 8.7/15.0 GB
get_details_by_id("L1002")
check_network_mode_preference()           → ok
can_send_mms()                            → still failing
check_wifi_status()                       → OFF
transfer_to_human_agents(...)             → transferred
```

At step 8, the agent sees `check_app_permissions` return "storage, phone" — SMS permission is missing. The fix is one call: `grant_app_permission("messaging", "sms")`. Instead the agent wanders off checking line details, data usage, Wi-Fi, and network mode before giving up.

The verifier can't help here. All the required diagnostic tools were called. The problem is the agent's failure to interpret a result it already received — no verifier can force that.

---

## Trace 4: Complex service issue, agent skips APN reset

**Task**: `airplane_mode_on|break_apn_settings|overdue_bill_suspension|unseat_sim_card` (service_issue)

Four things are broken at once. Agent needs to pay the bill, resume the line, turn off airplane mode, reset APN, re-seat SIM, and reboot.

```
get_customer_by_phone("555-123-2002")
get_bills_for_customer(C1001)             → B1234321 overdue
send_payment_request(C1001, B1234321)     → sent
make_payment()                            → $65 paid ✓
get_details_by_id("L1002")               → Suspended (correct line!)
resume_line(C1001, L1002)                 → Active ✓
reboot_device()                           → status: ✈️ Airplane Mode
toggle_airplane_mode()                    → OFF, but "No Signal"
toggle_data()                             → "Mobile Data is now OFF" (??)
check_network_status()                    → SIM missing, no_service
check_sim_status()                        → "No SIM card detected"
reseat_sim_card()                         → SIM re-seated
transfer_to_human_agents(...)             → transferred
```

The agent actually handles 6 out of 8 expected actions correctly — payment, resume, airplane mode, reboot, SIM — but never calls `reset_apn_settings`. After re-seating the SIM, it needed another reboot to pick up connectivity, but transferred instead.

The verifier allowed the transfer because `check_network_status` and `check_sim_status` were both called (the required diagnostics for service_issue). The verifier doesn't track which *fix* actions are missing, only which *diagnostic* actions.

---

## Root causes and verifier gaps

The failures cluster into 3 categories:

**1. Wrong line (62/66 failures).** The agent defaults to L1001 (the first in the list) instead of L1002 (the user's actual phone line). This poisons every downstream action. The verifier's SLM-based ARG rules were supposed to catch this but the `convo_text` fallback silently allowed all 133 wrong-line enable_roaming calls.

**2. Missing fix actions (traces 3, 4).** The agent runs diagnostics correctly — it even *sees* the problem (missing SMS permission, broken APN) — but doesn't call the fix. The verifier only checks whether diagnostics were run before escalation, not whether the agent acted on the results.

**3. Premature stops (12 failures).** The agent doesn't even try to transfer — it just issues `###STOP###` when the speed test or MMS check comes back with a bad-but-not-terrible result. The transfer-blocking rule can't help if there's no transfer to block.

---

## How to fix the verifier

### Fix 1: Remove the `convo_text` fallback (high impact)

The fallback in all 4 ARG rules is the main bug. Remove it. If the SLM can't match the line from the ticket text alone, fall through to the violation message. This would have caught all 133 wrong-line enable_roaming calls.

```python
# DELETE these lines from all 4 ARG rules:
convo_text = " ".join(str(m.get("content", "")) for m in conversation).lower()
if line_id_lower in convo_text or line_phone in convo_text:
    return None
```

### Fix 2: Add a cheap deterministic wrong-line rule (high impact, no SLM cost)

Skip SLM entirely for the common case. The agent always starts by calling `get_customer_by_phone("555-123-2002")`. Compare the user's phone (from that first call or from the ticket) against the line being modified:

```python
def rule_wrong_line_for_user(tool_name, tool_args, conversation, db):
    """Block tool calls that target a line whose phone doesn't match the user's."""
    if tool_name not in ("enable_roaming", "refuel_data", "resume_line"):
        return None
    line_id = tool_args.get("line_id", "")
    line = _find_line(db, line_id)
    if not line:
        return None
    # Find user's phone from first get_customer_by_phone call
    user_phone = _extract_user_phone(conversation)
    if user_phone and line.phone_number != user_phone:
        return f"Wrong line: {line_id} has phone {line.phone_number}, but user's phone is {user_phone}."
    return None
```

This is cheap (no SLM call), deterministic, and would catch 62 of 66 failures.

### Fix 3: Set `user_instructions` in solo mode

The `set_user_instructions()` call in the orchestrator only fires on user messages, which don't exist in solo mode. Add an init-time call so ARG rules get the clean ticket context.

### Fix 4: Add `check_apn_settings` / `grant_app_permission` to required diagnostics

For MMS issues, add `check_app_permissions` to the required-tools list. For service issues, add `check_apn_settings`. This won't force the agent to *act* on the results, but at least it'll run them before escalating.
