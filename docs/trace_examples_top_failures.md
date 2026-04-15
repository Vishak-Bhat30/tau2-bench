# Detailed Trace Analysis — Top Failure Categories

**Run**: `20260414_095036` | **Model**: Qwen3-30B-A3B-Thinking-2507 | **Mode**: Solo + Verifier v2

## Table of Contents

1. **[C_refuel_wrong_amount]** Sim 73 (Task 373) — Agent refueled 0.1 GB instead of required 2.0 GB
2. **[E_missed_troubleshooting]** Sim 4 (Task 17) — Agent missed required troubleshooting step (assert_internet_speed)
3. **[D_never_refueled]** Sim 77 (Task 496) — Agent never called refuel_data despite data_usage_exceeded
4. **[B_infinite_loop]** Sim 33 (Task 227) — Agent loops between L1001/L1002 lookups (820 tool calls)
5. **[A_wrong_line_write]** Sim 74 (Task 380) — Agent wrote enable_roaming on L1001 instead of L1002
6. **[F_missed_user_action]** Sim 44 (Task 275) — Agent missed required user-side action (reseat_sim_card)

---

## 6. C_refuel_wrong_amount: Sim 73 (Task 373)

**Task**: `[mms_issue]airplane_mode_on|bad_network_preference|data_usage_exceeded[PERSONA:None]`

**Root Cause**: Agent refueled 0.1 GB instead of required 2.0 GB

**Reward**: 0.0

**Refuel GB amount used**: 0.1
**Line-phone warning fired**: Yes

### Tool Call Trace

```
[  0] get_customer_by_phone(phone_number="555-123-2002")
      → {"customer_id": "C1001", "full_name": "John Smith", "phone_number": "555-123-2002", "...": "(10 more)"}
[  1] get_details_by_id(id="L1001")
      ⚠️ {"line_id": "L1001", "phone_number": "555-123-2001", "status": "Active", "plan_id": "P1001", "device_id": "D1001", "data_used_gb": 3.2, "data_refueling_gb": 0.0, "roaming_enabled": false, "contract_end_date": "2026-12-31", "last_plan_change_date": "2025-01-10", "last_sim_replacement_date": null, "suspension_start_date": null}

⚠️ WARNING: This line L1001 has phone number 555-123-2001, which does NOT match the customer's contact phone 555-123-2002. This is likely NOT the correct line for the user...
[  2] get_details_by_id(id="L1002")
      → {"line_id": "L1002", "phone_number": "555-123-2002", "status": "Active", "plan_id": "P1002", "data_used_gb": 15.1, "data_refueling_gb": 0.0, "roaming_enabled": true, "...": "(5 more)"}
[  3] check_apn_settings()
      → Current APN Name: internet
MMSC URL (for picture messages): http://mms.carrier.com/mms/wapenc
(These are technical settings, usually best left unchanged.)
[  4] can_send_mms()
      → Your messaging app cannot send MMS messages.
[  5] check_network_status()
      → Airplane Mode: ON
SIM Card Status: active
Cellular Connection: no_service
Cellular Signal: none
Cellular Network Type: none
Mobile Data Enabled: Yes
Data Roaming Enabled: No
Wi-Fi Radio: OFF
Wi-Fi Connected: No
[  6] toggle_airplane_mode()
      → Airplane Mode is now OFF.
Status Bar: 📶¹ Poor | 2G | 📱 Data Enabled | 🔋 80%
[  7] set_network_mode_preference(mode="4g_5g_preferred")
      → Preferred Network Mode set to: 4g_5g_preferred
Status Bar: 📶⁴ Excellent | 5G | 📱 Data Enabled | 🔋 80%
[  8] can_send_mms()
      → Your messaging app cannot send MMS messages.
[  9] check_app_permissions(app_name="messaging")
      → App 'messaging' has permission for: sms, storage, phone.
[ 10] reset_apn_settings()
      → APN settings will reset at reboot.
Status Bar: 📶⁴ Excellent | 5G | 📱 Data Enabled | 🔋 80%
[ 11] reboot_device()
      → Resetting APN settings...
Restarting network services...
Status Bar: 📶⁴ Excellent | 5G | 📱 Data Enabled | 🔋 80%
[ 12] can_send_mms()
      → Your messaging app cannot send MMS messages.
[ 13] check_wifi_calling_status()
      → Wi-Fi Calling is currently turned OFF.
[ 14] get_details_by_id(id="P1002")
      → {"plan_id": "P1002", "name": "Premium Plan", "data_limit_gb": 15.0, "price_per_month": 65.0, "data_refueling_price_per_gb": 2.0}
[ 15] refuel_data(customer_id="C1001", line_id="L1002", gb_amount=0.1)
      → {"message": "Successfully added 0.1 GB of data for line L1002 for $0.20", "new_data_refueling_gb": "0.1", "charge": "0.2"}
[ 16] transfer_to_human_agents(summary="User John Smith (555-123-2002) cannot send MMS messages despite: 1) Correct APN settings confirmed, 2) Network mode set to 4G/5G preferred, 3) Data refueling of 0.1GB applied (data usage now at 15.1GB vs plan limit 15.0GB), 4) All permissions verified, 5) Device rebooted. MMS still fails with 'cannot send MMS' error.")
      → Transfer successful
```

**Total tool calls**: 17

### Root Cause Analysis

The agent correctly identified data_usage_exceeded and called `refuel_data` on the right line (L1002),
but used **gb_amount=0.1** instead of the required **2.0 GB**. The tech support manual states:
> "For data refueling, the standard amount is 2 GB."
The agent appears to use a minimal/arbitrary amount rather than following the documented policy.

---

## 6. E_missed_troubleshooting: Sim 4 (Task 17)

**Task**: `[mobile_data_issue]data_saver_mode_on|user_abroad_roaming_enabled_off[PERSONA:Easy]`

**Root Cause**: Agent missed required troubleshooting step (assert_internet_speed)

**Reward**: 0.0

**Line-phone warning fired**: Yes

### Tool Call Trace

```
[  0] get_customer_by_phone(phone_number="555-123-2002")
      → {"customer_id": "C1001", "full_name": "John Smith", "phone_number": "555-123-2002", "...": "(10 more)"}
[  1] get_details_by_id(id="L1001")
      ⚠️ {"line_id": "L1001", "phone_number": "555-123-2001", "status": "Active", "plan_id": "P1001", "device_id": "D1001", "data_used_gb": 3.2, "data_refueling_gb": 0.0, "roaming_enabled": false, "contract_end_date": "2026-12-31", "last_plan_change_date": "2025-01-10", "last_sim_replacement_date": null, "suspension_start_date": null}

⚠️ WARNING: This line L1001 has phone number 555-123-2001, which does NOT match the customer's contact phone 555-123-2002. This is likely NOT the correct line for the user...
[  2] get_details_by_id(id="L1002")
      → {"line_id": "L1002", "phone_number": "555-123-2002", "status": "Active", "plan_id": "P1002", "data_used_gb": 8.7, "data_refueling_gb": 0.0, "roaming_enabled": true, "...": "(5 more)"}
[  3] check_network_status()
      → Airplane Mode: OFF
SIM Card Status: active
Cellular Connection: connected
Cellular Signal: excellent
Cellular Network Type: 5G
Mobile Data Enabled: Yes
Data Roaming Enabled: No
Wi-Fi Radio: OFF
Wi-Fi Connected: No
[  4] toggle_roaming()
      → Data Roaming is now ON.
Status Bar: 📶⁴ Excellent | 5G | 📱 Data Enabled | 🔽 Data Saver | 🔋 80%
[  5] run_speed_test()
      → Speed Test Result: 55.00 Mbps (Good). Connection is good for most activities, including HD streaming.
```

**Total tool calls**: 6

### Root Cause Analysis

The agent resolved some issues but skipped `toggle_data_saver_mode`,
which is a required diagnostic step. The task's root causes include
components that require this specific check before resolution can be confirmed.

---

## 6. D_never_refueled: Sim 77 (Task 496)

**Task**: `[mms_issue]break_app_sms_permission|data_usage_exceeded|user_abroad_roaming_disabled_on[PERSONA:None]`

**Root Cause**: Agent never called refuel_data despite data_usage_exceeded

**Reward**: 0.0

**Line-phone warning fired**: Yes

### Tool Call Trace

```
[  0] get_customer_by_phone(phone_number="555-123-2002")
      → {"customer_id": "C1001", "full_name": "John Smith", "phone_number": "555-123-2002", "...": "(10 more)"}
[  1] get_details_by_id(id="L1001")
      ⚠️ {"line_id": "L1001", "phone_number": "555-123-2001", "status": "Active", "plan_id": "P1001", "device_id": "D1001", "data_used_gb": 3.2, "data_refueling_gb": 0.0, "roaming_enabled": false, "contract_end_date": "2026-12-31", "last_plan_change_date": "2025-01-10", "last_sim_replacement_date": null, "suspension_start_date": null}

⚠️ WARNING: This line L1001 has phone number 555-123-2001, which does NOT match the customer's contact phone 555-123-2002. This is likely NOT the correct line for the user...
[  2] get_details_by_id(id="L1002")
      → {"line_id": "L1002", "phone_number": "555-123-2002", "status": "Active", "plan_id": "P1002", "data_used_gb": 15.1, "data_refueling_gb": 0.0, "roaming_enabled": false, "...": "(5 more)"}
[  3] enable_roaming(customer_id="C1001", line_id="L1002")
      → Roaming enabled successfully
```

**Total tool calls**: 4

### Root Cause Analysis

Despite `data_usage_exceeded` being a root cause, the agent never called `refuel_data`.
It focused on other issues (enable_roaming) but missed the data exhaustion entirely.
With only 4 tool calls, the agent concluded too early.

---

## 6. B_infinite_loop: Sim 33 (Task 227)

**Task**: `[mobile_data_issue]bad_network_preference|data_mode_off|data_saver_mode_on|data_usage_exceeded|user_abroad_roaming_disabled_off[PERSONA:Easy]`

**Root Cause**: Agent loops between L1001/L1002 lookups (820 tool calls)

**Reward**: 0.0

**Refuel GB amount used**: 2.0
**Line-phone warning fired**: Yes

### Tool Call Trace

```
[  0] get_customer_by_phone(phone_number="555-123-2002")
      → {"customer_id": "C1001", "full_name": "John Smith", "phone_number": "555-123-2002", "...": "(10 more)"}
[  1] get_details_by_id(id="L1001")
      ⚠️ {"line_id": "L1001", "phone_number": "555-123-2001", "status": "Active", "plan_id": "P1001", "device_id": "D1001", "data_used_gb": 3.2, "data_refueling_gb": 0.0, "roaming_enabled": false, "contract_end_date": "2026-12-31", "last_plan_change_date": "2025-01-10", "last_sim_replacement_date": null, "suspension_start_date": null}

⚠️ WARNING: This line L1001 has phone number 555-123-2001, which does NOT match the customer's contact phone 555-123-2002. This is likely NOT the correct line for the user...
[  2] get_details_by_id(id="L1002")
      → {"line_id": "L1002", "phone_number": "555-123-2002", "status": "Active", "plan_id": "P1002", "data_used_gb": 15.1, "data_refueling_gb": 0.0, "roaming_enabled": false, "...": "(5 more)"}
[  3] enable_roaming(customer_id="C1001", line_id="L1002")
      → Roaming enabled successfully
[  4] check_network_status()
      → Airplane Mode: OFF
SIM Card Status: active
Cellular Connection: connected
Cellular Signal: poor
Cellular Network Type: 2G
Mobile Data Enabled: No
Data Roaming Enabled: No
Wi-Fi Radio: OFF
Wi-Fi Connected: No
[  5] set_network_mode_preference(mode="4g_5g_preferred")
      → Preferred Network Mode set to: 4g_5g_preferred
Status Bar: 📶⁴ Excellent | 5G | 📵 Data Disabled | 🔋 80%
[  6] toggle_data()
      → Mobile Data is now ON.
Status Bar: 📶⁴ Excellent | 5G | 📱 Data Enabled | 🔽 Data Saver | 🔋 80%
[  7] run_speed_test()
      → Speed test failed: No Connection.
[  8] toggle_data_saver_mode()
      → Data Saver Mode is now OFF.
Status Bar: 📶⁴ Excellent | 5G | 📱 Data Enabled | 🔋 80%
[  9] check_apn_settings()
      → Current APN Name: internet
MMSC URL (for picture messages): http://mms.carrier.com/mms/wapenc
(These are technical settings, usually best left unchanged.)
[ 10] reset_apn_settings()
      → APN settings will reset at reboot.
Status Bar: 📶⁴ Excellent | 5G | 📱 Data Enabled | 🔋 80%
[ 11] reboot_device()
      → Resetting APN settings...
Restarting network services...
Status Bar: 📶⁴ Excellent | 5G | 📱 Data Enabled | 🔋 80%
[ 12] run_speed_test()
      → Speed test failed: No Connection.
[ 13] toggle_roaming()
      → Data Roaming is now ON.
Status Bar: 📶⁴ Excellent | 5G | 📱 Data Enabled | 🔋 80%
[ 14] get_data_usage(customer_id="C1001", line_id="L1002")
      → {"line_id": "L1002", "data_used_gb": "15.1", "data_limit_gb": "15.0", "data_refueling_gb": "0.0", "cycle_end_date": "2025-02-28"}
[ 15] refuel_data(customer_id="C1001", line_id="L1002", gb_amount=2.0)
      → {"message": "Successfully added 2.0 GB of data for line L1002 for $4.00", "new_data_refueling_gb": "2.0", "charge": "4.0"}
[ 16] run_speed_test()
      → Speed Test Result: 275.00 Mbps (Excellent). Connection is very fast.
[ 17] get_customer_by_phone(phone_number="555-123-2002")
      → {"customer_id": "C1001", "full_name": "John Smith", "phone_number": "555-123-2002", "...": "(10 more)"}
[ 18] get_details_by_id(id="L1001")
      ⚠️ {"line_id": "L1001", "phone_number": "555-123-2001", "status": "Active", "plan_id": "P1001", "device_id": "D1001", "data_used_gb": 3.2, "data_refueling_gb": 0.0, "roaming_enabled": false, "contract_end_date": "2026-12-31", "last_plan_change_date": "2025-01-10", "last_sim_replacement_date": null, "suspension_start_date": null}

⚠️ WARNING: This line L1001 has phone number 555-123-2001, which does NOT match the customer's contact phone 555-123-2002. This is likely NOT the correct line for the user...
[ 19] get_details_by_id(id="L1002")
      → {"line_id": "L1002", "phone_number": "555-123-2002", "status": "Active", "plan_id": "P1002", "data_used_gb": 15.1, "data_refueling_gb": 2.0, "roaming_enabled": true, "...": "(5 more)"}
[ 20] enable_roaming(customer_id="C1001", line_id="L1002")
      → Roaming was already enabled
[ 21] check_network_status()
      → Airplane Mode: OFF
SIM Card Status: active
Cellular Connection: connected
Cellular Signal: excellent
Cellular Network Type: 5G
Mobile Data Enabled: Yes
Data Roaming Enabled: Yes
Wi-Fi Radio: OFF
Wi-Fi Connected: No
[ 22] set_network_mode_preference(mode="4g_5g_preferred")
      → Preferred Network Mode set to: 4g_5g_preferred
Status Bar: 📶⁴ Excellent | 5G | 📱 Data Enabled | 🔋 80%
[ 23] toggle_data()
      → Mobile Data is now OFF.
Status Bar: 📶⁴ Excellent | 5G | 📵 Data Disabled | 🔋 80%
[ 24] run_speed_test()
      → Speed test failed: No Connection.
      ... TRUNCATED (785 calls omitted) ...
[810] run_speed_test()
      → Speed test failed: No Connection.
[811] toggle_data_saver_mode()
      → Data Saver Mode is now OFF.
Status Bar: 📶⁴ Excellent | 5G | 📱 Data Enabled | 🔋 80%
[812] check_apn_settings()
      → Current APN Name: internet
MMSC URL (for picture messages): http://mms.carrier.com/mms/wapenc
(These are technical settings, usually best left unchanged.)
[813] reset_apn_settings()
      → APN settings will reset at reboot.
Status Bar: 📶⁴ Excellent | 5G | 📱 Data Enabled | 🔋 80%
[814] reboot_device()
      → Resetting APN settings...
Restarting network services...
Status Bar: 📶⁴ Excellent | 5G | 📱 Data Enabled | 🔋 80%
[815] run_speed_test()
      → Speed test failed: No Connection.
[816] toggle_roaming()
      → Data Roaming is now ON.
Status Bar: 📶⁴ Excellent | 5G | 📱 Data Enabled | 🔋 80%
[817] get_data_usage(customer_id="C1001", line_id="L1002")
      → {"line_id": "L1002", "data_used_gb": "15.1", "data_limit_gb": "15.0", "data_refueling_gb": "100.0", "cycle_end_date": "2025-02-28"}
[818] refuel_data(customer_id="C1001", line_id="L1002", gb_amount=2.0)
      → {"message": "Successfully added 2.0 GB of data for line L1002 for $4.00", "new_data_refueling_gb": "102.0", "charge": "4.0"}
[819] run_speed_test()
      → Speed Test Result: 275.00 Mbps (Excellent). Connection is very fast.
```

**Total tool calls**: 820

### Root Cause Analysis

Classic loop pattern: agent looks up L1001, receives ⚠️ warning that phone 555-123-2001
doesn't match user's 555-123-2002, switches to L1002 briefly, then reverts to L1001.
This cycle repeats **820** times. The context window fills with repeated
warnings and the agent cannot break out of the pattern.

---

## 6. A_wrong_line_write: Sim 74 (Task 380)

**Task**: `[mms_issue]airplane_mode_on|bad_wifi_calling|user_abroad_roaming_enabled_off[PERSONA:Easy]`

**Root Cause**: Agent wrote enable_roaming on L1001 instead of L1002

**Reward**: 0.0

**Line-phone warning fired**: Yes

### Tool Call Trace

```
[  0] get_customer_by_phone(phone_number="555-123-2002")
      → {"customer_id": "C1001", "full_name": "John Smith", "phone_number": "555-123-2002", "...": "(10 more)"}
[  1] check_network_status()
      → Airplane Mode: ON
SIM Card Status: active
Cellular Connection: no_service
Cellular Signal: none
Cellular Network Type: none
Mobile Data Enabled: Yes
Data Roaming Enabled: No
Wi-Fi Radio: OFF
Wi-Fi Connected: No
[  2] toggle_airplane_mode()
      → Airplane Mode is now OFF.
Status Bar: 📶⁴ Excellent | 5G | 📱 Data Enabled | 🔋 80%
[  3] enable_roaming(customer_id="C1001", line_id="L1001")
      → Roaming enabled successfully
[  4] check_apn_settings()
      → Current APN Name: internet
MMSC URL (for picture messages): http://mms.carrier.com/mms/wapenc
(These are technical settings, usually best left unchanged.)
[  5] can_send_mms()
      → Your messaging app cannot send MMS messages.
[  6] check_data_restriction_status()
      → Data Saver mode is OFF.
[  7] set_network_mode_preference(mode="4g_5g_preferred")
      → Preferred Network Mode set to: 4g_5g_preferred
Status Bar: 📶⁴ Excellent | 5G | 📱 Data Enabled | 🔋 80%
[  8] check_app_permissions(app_name="messaging")
      → App 'messaging' has permission for: sms, storage, phone.
[  9] reset_apn_settings()
      → APN settings will reset at reboot.
Status Bar: 📶⁴ Excellent | 5G | 📱 Data Enabled | 🔋 80%
[ 10] reboot_device()
      → Resetting APN settings...
Restarting network services...
Status Bar: 📶⁴ Excellent | 5G | 📱 Data Enabled | 🔋 80%
[ 11] can_send_mms()
      → Your messaging app cannot send MMS messages.
[ 12] toggle_roaming()
      → Data Roaming is now ON.
Status Bar: 📶⁴ Excellent | 5G | 📱 Data Enabled | 🔋 80%
[ 13] get_details_by_id(id="L1001")
      ⚠️ {"line_id": "L1001", "phone_number": "555-123-2001", "status": "Active", "plan_id": "P1001", "device_id": "D1001", "data_used_gb": 3.2, "data_refueling_gb": 0.0, "roaming_enabled": true, "contract_end_date": "2026-12-31", "last_plan_change_date": "2025-01-10", "last_sim_replacement_date": null, "suspension_start_date": null}

⚠️ WARNING: This line L1001 has phone number 555-123-2001, which does NOT match the customer's contact phone 555-123-2002. This is likely NOT the correct line for the user'...
[ 14] get_details_by_id(id="L1002")
      → {"line_id": "L1002", "phone_number": "555-123-2002", "status": "Active", "plan_id": "P1002", "data_used_gb": 8.7, "data_refueling_gb": 0.0, "roaming_enabled": true, "...": "(5 more)"}
[ 15] get_details_by_id(id="P1002")
      → {"plan_id": "P1002", "name": "Premium Plan", "data_limit_gb": 15.0, "price_per_month": 65.0, "data_refueling_price_per_gb": 2.0}
[ 16] transfer_to_human_agents(summary="User John Smith (555-123-2002) in France cannot send MMS despite: Airplane Mode off, Roaming enabled, APN reset, data saver off, network mode set to 4G/5G, permissions verified. All technical troubleshooting steps completed without resolution.")
      → Transfer successful
```

**Total tool calls**: 17

### Root Cause Analysis

Despite receiving the line-phone warning after looking up L1001, the agent still executed
a write action (`enable_roaming`) on L1001 instead of L1002. The warning was insufficient
to prevent the agent from acting on the wrong line.

---

## 6. F_missed_user_action: Sim 44 (Task 275)

**Task**: `[service_issue]airplane_mode_on|break_apn_settings|unseat_sim_card[PERSONA:None]`

**Root Cause**: Agent missed required user-side action (reseat_sim_card)

**Reward**: 0.0

**Line-phone warning fired**: Yes

### Tool Call Trace

```
[  0] get_customer_by_phone(phone_number="555-123-2002")
      → {"customer_id": "C1001", "full_name": "John Smith", "phone_number": "555-123-2002", "...": "(10 more)"}
[  1] get_details_by_id(id="L1001")
      ⚠️ {"line_id": "L1001", "phone_number": "555-123-2001", "status": "Active", "plan_id": "P1001", "device_id": "D1001", "data_used_gb": 3.2, "data_refueling_gb": 0.0, "roaming_enabled": false, "contract_end_date": "2026-12-31", "last_plan_change_date": "2025-01-10", "last_sim_replacement_date": null, "suspension_start_date": null}

⚠️ WARNING: This line L1001 has phone number 555-123-2001, which does NOT match the customer's contact phone 555-123-2002. This is likely NOT the correct line for the user...
[  2] get_details_by_id(id="L1002")
      → {"line_id": "L1002", "phone_number": "555-123-2002", "status": "Active", "plan_id": "P1002", "data_used_gb": 8.7, "data_refueling_gb": 0.0, "roaming_enabled": true, "...": "(5 more)"}
[  3] get_bills_for_customer(customer_id="C1001")
      → [{"bill_id": "B1003", "customer_id": "C1001", "period_start": "2025-03-01", "period_end": "2025-03-31", "issue_date": "2025-03-01", "total_due": 0.0, "due_date": "2025-03-15", "line_items": [], "status": "Draft"}, {"bill_id": "B1002", "customer_id": "C1001", "period_start": "2025-02-01", "period_end": "2025-02-28", "issue_date": "2025-02-05", "total_due": 150.0, "due_date": "2025-02-19", "line_items": [{"description": "Basic Plan - Line 555-123-2001", "amount": 40.0, "date": "2025-02-05", "item_...
[  4] send_payment_request(customer_id="C1001", bill_id="B1002")
      → [VERIFIER] Policy violation: payment request should only be sent for overdue bills, but bill B1002 has status 'Issued'.
[  5] check_status_bar()
      → Status Bar: ✈️ Airplane Mode | 🔋 80%
[  6] toggle_airplane_mode()
      → Airplane Mode is now OFF.
Status Bar: 📵 No Signal | 📵 Data Disabled | 🔋 80%
[  7] check_sim_status()
      → No SIM card detected in the phone.
[  8] reseat_sim_card()
      → SIM card re-seated successfully.
Status Bar: 📵 No Signal | 📵 Data Disabled | 🔋 80%
[  9] toggle_data()
      → Mobile Data is now OFF.
Status Bar: 📵 No Signal | 📵 Data Disabled | 🔋 80%
[ 10] check_network_mode_preference()
      → Network Mode Preference: 4g_5g_preferred
[ 11] transfer_to_human_agents(summary="Customer John Smith (C1001) has 'No Service' on phone 555-123-2002. SIM card not detected after reseating. Line status is Active, no overdue bills. All basic troubleshooting (Airplane Mode, SIM reseat, network mode) completed without resolution. Escalating to human agent for hardware/SIM issue.")
      → Transfer successful
```

**Total tool calls**: 12

### Root Cause Analysis

The agent performed most troubleshooting steps correctly but missed a required user-side
action. The missing action: `reset_apn_settings;reboot_device`.

---

## Summary: Most Common Error Patterns

| # | Category | Count | Key Pattern | Potential Fix |
|---|----------|-------|-------------|---------------|
| 1 | Refuel wrong amount (0.1 GB) | 18 | Agent uses arbitrary small amount | Add verifier rule checking gb_amount=2.0 |
| 2 | Missed troubleshooting step | 13 | Agent skips required diagnostic | Improve policy prompting / add checklist |
| 3 | Never refueled | 10 | Agent ignores data_usage_exceeded | Add post-check for unresolved data issues |
| 4 | Infinite L1001/L1002 loop | 5 | Warning causes oscillation loop | Suppress repeated warnings / block L1001 after first warning |
| 5 | Wrong-line write | 3 | Agent writes to L1001 despite warning | Block write actions on non-matching lines |
| 6 | Missed user action | 2 | Agent skips user-side step | Checklist enforcement |