# Failure Analysis Report — v4 Run (61.4%)

**Run:** `20260415_100809` | **Agent:** Qwen3-30B-A3B-Thinking-2507 (Solo Mode) | **Date:** 2026-04-15

## Summary

| Metric | Value |
|---|---|
| Total tasks | 114 |
| Passed | 70 (61.4%) |
| Failed | 44 (38.6%) |
| ENV assertion pass rate | 158/202 (78.2%) |
| ACTION check pass rate | 456/504 (90.5%) |

## Failure Breakdown

| # | Category | Tasks | Root Cause |
|---|---|---|---|
| 1 | MMS: Missing `grant_app_permission` | 11 | Agent doesn't recognize missing SMS/storage permission |
| 2 | MMS: Missing `toggle_wifi_calling` | 5 | Agent never checks or toggles Wi-Fi calling |
| 3 | Speed: Incomplete troubleshooting | 7 | Agent stops at "Good" speed, doesn't reach "Excellent" |
| 4 | MMS: Missing `toggle_roaming` | 3 | Agent calls `enable_roaming` instead of `toggle_roaming` |
| 5 | Escalation: Didn't transfer to human | 3 | Agent doesn't recognize locked SIM needs escalation |
| 6 | Service: Not fully restored | 3 | Agent pays bill but skips post-payment troubleshooting |
| 7 | Data status: Mobile data not enabled | 3 | Agent toggles in wrong order, creates loops |
| 8 | Infinite loop / max_steps | 3 | Agent repeats same 10-20 step cycle 40-60+ times |
| 9 | Refuel: Wrong/missing amount | 2 | Agent skips refuel or uses wrong amount |
| 10 | MMS: Other (mixed/loops) | 4 | Combination of above issues or edge cases |
| | **TOTAL** | **44** | |

---

## 1. MMS: Missing `grant_app_permission` (11 tasks) — LARGEST CATEGORY

**Impact:** 25% of all failures

### What happens

The agent needs to grant the messaging app missing permissions (`sms` or `storage`) but fails to do so, even though:
- In **8/11 tasks**, the agent calls `check_app_permissions("messaging")` and sees the result
- In **3/11 tasks**, the agent doesn't even check permissions

### Root cause: Agent doesn't interpret permission output correctly

When `check_app_permissions` returns:
```
App 'messaging' has permission for: storage, phone.
```
The agent sees "storage" and "phone" listed but **does not realize "sms" is missing**. It proceeds to other troubleshooting steps (reset APN, reboot) without granting the missing permission.

### Example trace: `break_app_sms_permission|data_mode_off`

```
[1] get_customer_by_phone → C1001
[2] get_details_by_id → L1001
[3] get_details_by_id → L1002 (correct line)
[4] check_network_status → Mobile Data: No
[5] toggle_data → Data ON ✓
[6] get_data_usage → 8.7/15 GB (under limit)
[7] check_apn_settings → MMSC URL correct
[8] can_send_mms → CANNOT send MMS ✗
[9] check_app_permissions → "storage, phone" (sms MISSING!)
    ⚠️ Agent SEES this but doesn't grant sms
[10] reset_apn_settings
[11] reboot_device
[12] transfer_to_human_agents → gives up
```

### Permission check results across all 11 tasks

| Tasks | `check_app_permissions` called? | Response | Needed permission | Granted? |
|---|---|---|---|---|
| 8 | Yes | "storage, phone" | sms | No (7), Yes (1) |
| 3 | No | — | storage / sms+storage | No |

### Suggested fix

- **Verifier rule**: After `check_app_permissions` returns, if required permissions (sms, storage) are not in the list, inject a warning: "The messaging app is missing {permission} permission. Call grant_app_permission to fix it."
- **Policy hint**: Add to troubleshooting workflow: "MMS requires sms, storage, and phone permissions. If any are missing, grant them."

---

## 2. MMS: Missing `toggle_wifi_calling` (5 tasks)

**Impact:** 11% of all failures

### What happens

When Wi-Fi calling is enabled and interfering with MMS, the agent needs to toggle it off. But the agent **never calls `check_wifi_calling_status`** and **never calls `toggle_wifi_calling`** in any of the 5 failed tasks.

### Root cause: Agent doesn't know Wi-Fi calling can interfere with MMS

The agent's troubleshooting checklist doesn't include Wi-Fi calling. It checks:
- APN settings ✓
- Mobile data ✓
- Network mode ✓
- App permissions ✓
- Data usage ✓

But never:
- Wi-Fi calling status ✗

### Tool usage stats

Across **all 114 tasks**:
- `check_wifi_calling_status`: called only 26 times (vs 532 for `check_apn_settings`)
- `toggle_wifi_calling`: called only 17 times

### Suggested fix

- **Policy hint**: Add "Check Wi-Fi calling status — if enabled, toggle it off as it can interfere with MMS" to the MMS troubleshooting workflow
- **Verifier rule**: If `can_send_mms` returns false after all other steps, suggest checking Wi-Fi calling

---

## 3. Speed: Incomplete Troubleshooting (7 tasks)

**Impact:** 16% of all failures

### What happens

The agent successfully fixes most issues (toggles airplane mode, enables roaming, sets network preference) but stops troubleshooting when `run_speed_test` returns **"Good" (27-55 Mbps)**. The evaluation expects **"Excellent" (200 Mbps)**.

### Root cause: Agent accepts "Good" as sufficient

The agent sees:
```
Speed Test Result: 55.00 Mbps (Good). Connection is good for most activities, including HD streaming
```
...and concludes the issue is resolved. But the customer's connection should be "Excellent" at 200 Mbps.

### Missed actions per task

| Issue present | Missed action | Speed result | Tasks |
|---|---|---|---|
| `data_saver_mode_on` | `toggle_data_saver_mode` | 55 Mbps (Good) | 3 |
| `bad_vpn` | `disconnect_vpn` | 27.5 Mbps (Good) | 3 |
| Mixed | Various | 44 Mbps (Good) | 1 |

### Pattern: VPN and Data Saver are "invisible" to the agent

- **VPN**: Agent never calls `check_vpn_status` (called only 1 time across all 114 tasks!) or `disconnect_vpn` (12 times total). It doesn't know to look for VPN issues.
- **Data Saver**: Agent calls `toggle_data_saver_mode` only 87 times total. When it does check via `check_data_restriction_status`, it sometimes doesn't act on the result.

### Suggested fix

- **Verifier rule**: After `run_speed_test` returns anything below "Excellent", warn: "Speed is not optimal. Check VPN, data saver mode, and network preference."
- **Policy hint**: "A resolved mobile data issue should show 'Excellent' speed. If speed test shows 'Good' or lower, continue troubleshooting: check VPN, data saver mode, and network mode preference."

---

## 4. MMS: Missing `toggle_roaming` (3 tasks)

**Impact:** 7% of all failures

### What happens

The evaluation expects the agent to call `toggle_roaming` but the agent calls `enable_roaming` instead.

### Root cause: Wrong tool choice

All 3 tasks have `user_abroad_roaming_disabled_off` — roaming is disabled and needs to be turned on. The agent correctly identifies this and calls `enable_roaming`, but the evaluation checks for `toggle_roaming`.

| Task | `toggle_roaming` called | `enable_roaming` called |
|---|---|---|
| All 3 failed tasks | No | Yes |
| Passing tasks with roaming issues | Yes | No |

### Suggested fix

- **Verifier rule**: When agent calls `enable_roaming`, convert or warn to use `toggle_roaming` instead
- **Or**: Accept `enable_roaming` as equivalent to `toggle_roaming` in evaluation

---

## 5. Escalation: Didn't Transfer to Human (3 tasks)

**Impact:** 7% of all failures

### What happens

All 3 tasks involve `lock_sim_card_pin` — the SIM is locked with a PIN. Per policy, the agent cannot unlock a SIM card and must transfer to a human agent. Instead, the agent:
1. Looks up customer → finds overdue bill
2. Processes payment
3. Resumes the line
4. **Stops** — never transfers to human

### Root cause: Agent resolves the bill issue but doesn't recognize SIM lock

The agent successfully handles the `overdue_bill_suspension` component but doesn't detect or act on the `lock_sim_card_pin` issue. After resuming the line, it considers the task complete.

### Example trace: `lock_sim_card_pin|overdue_bill_suspension`

```
[1] get_customer_by_phone → C1001
[2] get_bills_for_customer → overdue bill B1234321
[3] send_payment_request → sent
[4] check_payment_request → payment received
[5] make_payment → bill paid ✓
[6] get_details_by_id → L1002
[7] resume_line → line resumed ✓
    ⚠️ Agent STOPS here — doesn't check SIM status or transfer to human
```

### Suggested fix

- **Policy hint**: "After resolving billing issues, verify the service is fully working. If the SIM is locked, transfer to a human agent."
- **Verifier rule**: After `resume_line`, check if service is actually restored. If not, suggest further troubleshooting.

---

## 6. Service: Not Fully Restored (3 tasks)

**Impact:** 7% of all failures

### What happens

Similar to escalation failures — the agent pays the bill and resumes the line but stops without performing physical troubleshooting steps needed for `unseat_sim_card` and `break_apn_settings`.

### Missed actions

| Task | Missed steps |
|---|---|
| `overdue_bill_suspension\|unseat_sim_card` | `reseat_sim_card`, `reboot_device` |
| `break_apn_settings\|overdue_bill_suspension\|unseat_sim_card` | `reset_apn_settings`, `reseat_sim_card`, `reboot_device` x2 |
| `airplane_mode_on\|break_apn_settings\|overdue_bill_suspension\|unseat_sim_card` | `reset_apn_settings` (did reseat + reboot) |

### Root cause: Agent doesn't verify service after payment

After `resume_line`, the agent declares success without checking if the phone actually works. The SIM card is physically unseated, requiring `reseat_sim_card` + `reboot_device`.

---

## 7. Data Status: Mobile Data Not Enabled (3 tasks)

**Impact:** 7% of all failures

### What happens

The agent toggles airplane mode, data, roaming in an order that leaves mobile data OFF at the end. In one task, the agent made **76 tool calls** in a repetitive loop, toggling the same settings repeatedly.

### Root cause: Toggle order creates oscillation

Example: Agent calls `toggle_airplane_mode` (ON→OFF), then later calls it again (OFF→ON), undoing its own fix. This creates a cycle where the agent keeps flipping the same switches.

---

## 8. Infinite Loops (3 tasks)

**Impact:** 7% of all failures

### What happens

The agent gets stuck in a repeating cycle of 10-20 tool calls, running the same diagnostic sequence over and over.

| Task | Tool calls | Termination |
|---|---|---|
| `data_usage_exceeded\|user_abroad_roaming_enabled_off` | 1,073 | max_steps |
| `bad_vpn\|data_saver_mode_on\|user_abroad_roaming_disabled_on` | 1,016 | max_steps |
| `airplane_mode_on\|break_apn_settings\|overdue_bill_suspension` | 336 | too_many_errors |

Additionally, 2 tasks in the MMS_OTHER category also had infinite loops (845 and 1,023 calls).

### Root cause: Agent doesn't track what it's already tried

The agent repeats the exact same sequence: `check_network_status → toggle_airplane_mode → set_network_mode_preference → run_speed_test → check_apn_settings → reset_apn_settings → reboot_device → ...` without realizing it already tried all these steps.

### Suggested fix

- **Verifier rule**: Detect when the agent is repeating the same tool call sequence 3+ times and inject: "You are repeating the same steps. If these steps haven't resolved the issue, try different approaches or transfer to a human agent."

---

## 9. Refuel: Wrong/Missing Amount (2 tasks)

**Impact:** 5% of all failures

Despite the ticket fix adding the 2.0 GB refuel hint, 2 tasks still failed on `assert_data_refueling_amount`. These are edge cases where the agent either didn't refuel at all or the refuel was applied to the wrong context.

---

## Top-Level ENV Assertion Failures

| Assertion | Failures | Primary cause |
|---|---|---|
| `assert_can_send_mms` | 22 | Missing permissions, Wi-Fi calling, roaming |
| `assert_internet_speed` | 11 | VPN, data saver not addressed |
| `assert_data_refueling_amount` | 5 | Skipped/wrong refuel |
| `assert_mobile_data_status` | 3 | Toggle oscillation |
| `assert_service_status` | 3 | No post-payment troubleshooting |

## Top Missed Actions

| Action | Missed count | Why |
|---|---|---|
| `grant_app_permission(sms)` | 9 | Agent doesn't interpret permission check output |
| `toggle_wifi_calling` | 8 | Agent never checks Wi-Fi calling |
| `toggle_roaming` | 7 | Agent uses `enable_roaming` instead |
| `toggle_data_saver_mode` | 4 | Agent accepts "Good" speed |
| `reseat_sim_card` | 4 | Agent skips physical troubleshooting |
| `disconnect_vpn` | 3 | Agent never checks VPN status |
| `transfer_to_human_agents` | 3 | Agent doesn't recognize SIM lock |
| `reboot_device` | 3 | Skipped in service tasks |
| `reset_apn_settings` | 2 | Skipped in service tasks |

## Actionable Recommendations (Ordered by Impact)

### High Impact (would fix 11+ tasks)
1. **App permission awareness**: Verifier/policy to ensure agent grants missing sms/storage permissions when `check_app_permissions` shows them absent

### Medium Impact (would fix 5-8 tasks)
2. **Wi-Fi calling in MMS workflow**: Add `check_wifi_calling_status` → `toggle_wifi_calling` to MMS troubleshooting steps
3. **Speed threshold awareness**: Agent should continue troubleshooting if speed is below "Excellent" — check VPN, data saver

### Lower Impact (would fix 3-4 tasks each)
4. **`toggle_roaming` vs `enable_roaming`**: Either verifier rule to redirect or evaluation fix to accept both
5. **SIM lock detection**: After `resume_line`, check `check_sim_status` and escalate if locked
6. **Post-payment verification**: After paying bill + resuming line, verify service status and continue troubleshooting if needed
7. **Loop detection**: Detect and break infinite tool call loops

## Tool Usage Heat Map (All 114 Tasks)

| Tool | Total calls | Notes |
|---|---|---|
| `get_details_by_id` | 1,223 | Heavy lookup usage |
| `can_send_mms` | 674 | Frequent MMS checks |
| `run_speed_test` | 598 | Frequent speed checks |
| `get_customer_by_phone` | 561 | |
| `check_apn_settings` | 532 | |
| `check_network_status` | 519 | |
| `reboot_device` | 445 | |
| `reset_apn_settings` | 331 | |
| `grant_app_permission` | 245 | Called but not always correctly |
| `check_app_permissions` | 205 | |
| `toggle_wifi_calling` | **17** | Severely underused |
| `disconnect_vpn` | **12** | Severely underused |
| `check_vpn_status` | **1** | Almost never used |
