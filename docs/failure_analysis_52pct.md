# Telecom Solo Verifier Run — Failure Analysis
**Run**: `20260414_095036`  
**Model**: Qwen3-30B-A3B-Thinking-2507  
**Mode**: Solo + Verifier (with line-phone warning)  
**Tasks**: 114  
**Average Reward**: 52.6%  

## Reward Component Breakdown

| Component | Tasks | Pass | Rate |
|-----------|-------|------|------|
| ENV_ASSERTION only | 89 | 41 | 46.1% |
| ENV_ASSERTION + ACTION | 20 | 19 | 95.0% |
| **Overall** | **114** | **60** | **52.6%** |

## Root Cause Summary

| Category | Count | Description |
|----------|-------|-------------|
| **A. Wrong-line write (L1001)** | 3 | Agent called a write tool (enable_roaming, refuel_data) on L1001 instead of L1002 |
| **B. Infinite L1001/L1002 loop** | 5 | Agent keeps re-looking-up L1001, gets warned, corrects to L1002, then forgets and looks up L1001 again in a loop |
| **C. Refueled wrong amount (0.1 GB)** | 18 | Agent called refuel_data on correct line but with gb_amount=0.1 instead of 2.0 |
| **D. Never refueled** | 10 | Agent should have called refuel_data but never did |
| **E. Missed troubleshooting step** | 13 | Agent missed a required user-side troubleshooting action |
| **F. Missed user action** | 2 | Agent missed a required user action (toggle_roaming, reseat_sim, etc.) |
| **G. Missed transfer** | 1 | Agent should have transferred to human agent but did not |
| **H. Other/environment** | 2 | Task failed for other reasons (env state not resolved despite correct actions) |
| **Total Failed** | **54** | |

## A. Wrong-line write (L1001) (3 tasks)

> Agent called a write tool (enable_roaming, refuel_data) on L1001 instead of L1002

### Sim 74 (Task 380): `[mms_issue]airplane_mode_on|bad_wifi_calling|user_abroad_roaming_enabled_off[PERSONA:Easy]`

- **Warning fired**: True
- **Lines looked up**: L1001 → L1002
- **Write actions**: enable_roaming(L1001)
- **Failed env assertions**: assert_can_send_mms
- **Missing actions**: toggle_wifi_calling
- **Passed actions**: toggle_airplane_mode, toggle_roaming
- **Total tool calls**: 17

### Sim 103 (Task 2209): `[mms_issue]airplane_mode_on|bad_network_preference|bad_wifi_calling|break_app_storage_permission|data_mode_off|data_usage_exceeded|unseat_sim_card|user_abroad_roaming_enabled_off[PERSONA:Hard]`

- **Warning fired**: True
- **Lines looked up**: L1001 → L1002
- **Write actions**: enable_roaming(L1001)
- **Failed env assertions**: assert_can_send_mms, assert_data_refueling_amount
- **Missing actions**: refuel_data, toggle_roaming
- **Passed actions**: toggle_airplane_mode, set_network_mode_preference, toggle_wifi_calling, grant_app_permission, toggle_data, reseat_sim_card
- **Total tool calls**: 23

### Sim 111 (Task 2283): `[mms_issue]airplane_mode_on|bad_network_preference|bad_wifi_calling|break_apn_mms_setting|break_app_storage_permission|data_mode_off|data_usage_exceeded|unseat_sim_card|user_abroad_roaming_disabled_off[PERSONA:Easy]`

- **Warning fired**: False
- **Lines looked up**: none
- **Write actions**: enable_roaming(L1001)
- **Failed env assertions**: assert_can_send_mms, assert_data_refueling_amount
- **Missing actions**: refuel_data, enable_roaming
- **Passed actions**: toggle_airplane_mode, set_network_mode_preference, toggle_wifi_calling, reset_apn_settings, reboot_device, grant_app_permission, toggle_data, reseat_sim_card, toggle_roaming
- **Total tool calls**: 23

## B. Infinite L1001/L1002 loop (5 tasks)

> Agent keeps re-looking-up L1001, gets warned, corrects to L1002, then forgets and looks up L1001 again in a loop

### Sim 33 (Task 227): `[mobile_data_issue]bad_network_preference|data_mode_off|data_saver_mode_on|data_usage_exceeded|user_abroad_roaming_disabled_off[PERSONA:Easy]`

- **Warning fired**: True
- **Lines looked up**: L1001 → L1002
- **Write actions**: enable_roaming(L1002), refuel_data(L1002)
- **Failed env assertions**: assert_data_refueling_amount
- **Passed env assertions**: assert_mobile_data_status, assert_internet_speed
- **Passed actions**: set_network_mode_preference, toggle_data, toggle_data_saver_mode, refuel_data, enable_roaming, toggle_roaming
- **Total tool calls**: 820

### Sim 45 (Task 208): `[mobile_data_issue]airplane_mode_on|bad_network_preference|data_saver_mode_on|data_usage_exceeded|user_abroad_roaming_disabled_off[PERSONA:None]`

- **Warning fired**: True
- **Lines looked up**: L1001 → L1002
- **Write actions**: enable_roaming(L1002), refuel_data(L1002)
- **Total tool calls**: 1148

### Sim 49 (Task 235): `[mobile_data_issue]airplane_mode_on|bad_network_preference|bad_vpn|data_mode_off|data_usage_exceeded|user_abroad_roaming_enabled_off[PERSONA:Easy]`

- **Warning fired**: True
- **Lines looked up**: L1001 → L1002
- **Write actions**: refuel_data(L1002)
- **Total tool calls**: 1432

### Sim 57 (Task 252): `[mobile_data_issue]airplane_mode_on|bad_network_preference|bad_vpn|data_mode_off|data_saver_mode_on|data_usage_exceeded|user_abroad_roaming_disabled_on[PERSONA:None]`

- **Warning fired**: True
- **Lines looked up**: L1001 → L1002
- **Write actions**: enable_roaming(L1002), refuel_data(L1002)
- **Total tool calls**: 1432

### Sim 93 (Task 463): `[mms_issue]bad_network_preference|data_mode_off|user_abroad_roaming_disabled_on[PERSONA:None]`

- **Warning fired**: True
- **Lines looked up**: L1001 x93, L1002 x93 (loop)
- **Write actions**: enable_roaming(L1002)
- **Total tool calls**: 837

## C. Refueled wrong amount (0.1 GB) (18 tasks)

> Agent called refuel_data on correct line but with gb_amount=0.1 instead of 2.0

### Sim 69 (Task 329): `[mms_issue]break_app_storage_permission|data_usage_exceeded[PERSONA:Easy]`

- **Warning fired**: True
- **Lines looked up**: L1001 → L1002
- **Write actions**: refuel_data(L1002)
- **Failed env assertions**: assert_data_refueling_amount
- **Passed env assertions**: assert_can_send_mms
- **Missing actions**: refuel_data
- **Passed actions**: grant_app_permission
- **Refuel args used**: `{'customer_id': 'C1001', 'line_id': 'L1002', 'gb_amount': 0.1}`
- **Total tool calls**: 18

### Sim 71 (Task 330): `[mms_issue]break_app_both_permissions|data_usage_exceeded[PERSONA:Hard]`

- **Warning fired**: True
- **Lines looked up**: L1001 → L1002
- **Write actions**: refuel_data(L1002)
- **Failed env assertions**: assert_can_send_mms, assert_data_refueling_amount
- **Missing actions**: refuel_data
- **Passed actions**: grant_app_permission, grant_app_permission
- **Refuel args used**: `{'customer_id': 'C1001', 'line_id': 'L1002', 'gb_amount': 0.1}`
- **Total tool calls**: 22

### Sim 73 (Task 373): `[mms_issue]airplane_mode_on|bad_network_preference|data_usage_exceeded[PERSONA:None]`

- **Warning fired**: True
- **Lines looked up**: L1001 → L1002
- **Write actions**: refuel_data(L1002)
- **Failed env assertions**: assert_can_send_mms, assert_data_refueling_amount
- **Missing actions**: refuel_data
- **Passed actions**: toggle_airplane_mode, set_network_mode_preference
- **Refuel args used**: `{'customer_id': 'C1001', 'line_id': 'L1002', 'gb_amount': 0.1}`
- **Total tool calls**: 17

### Sim 76 (Task 452): `[mms_issue]bad_wifi_calling|data_mode_off|data_usage_exceeded[PERSONA:Easy]`

- **Warning fired**: True
- **Lines looked up**: L1001 → L1002
- **Write actions**: refuel_data(L1002)
- **Failed env assertions**: assert_can_send_mms, assert_data_refueling_amount
- **Missing actions**: refuel_data
- **Passed actions**: toggle_wifi_calling, toggle_data
- **Refuel args used**: `{'customer_id': 'C1001', 'line_id': 'L1002', 'gb_amount': 0.1}`
- **Total tool calls**: 22

### Sim 82 (Task 658): `[mms_issue]airplane_mode_on|break_app_both_permissions|data_usage_exceeded|user_abroad_roaming_disabled_off[PERSONA:None]`

- **Warning fired**: True
- **Lines looked up**: L1001 → L1002
- **Write actions**: enable_roaming(L1002), refuel_data(L1002)
- **Failed env assertions**: assert_can_send_mms, assert_data_refueling_amount
- **Missing actions**: refuel_data
- **Passed actions**: toggle_airplane_mode, grant_app_permission, grant_app_permission, enable_roaming, toggle_roaming
- **Refuel args used**: `{'customer_id': 'C1001', 'line_id': 'L1002', 'gb_amount': 0.1}`
- **Total tool calls**: 25

### Sim 85 (Task 837): `[mms_issue]break_apn_mms_setting|data_mode_off|data_usage_exceeded|user_abroad_roaming_disabled_on[PERSONA:Hard]`

- **Warning fired**: True
- **Lines looked up**: L1001 → L1002
- **Write actions**: enable_roaming(L1002), refuel_data(L1002)
- **Failed env assertions**: assert_can_send_mms, assert_data_refueling_amount
- **Missing actions**: refuel_data
- **Passed actions**: reset_apn_settings, reboot_device, toggle_data, enable_roaming
- **Refuel args used**: `{'customer_id': 'C1001', 'line_id': 'L1002', 'gb_amount': 0.1}`
- **Total tool calls**: 22

### Sim 89 (Task 1408): `[mms_issue]bad_network_preference|break_app_sms_permission|data_mode_off|data_usage_exceeded|user_abroad_roaming_enabled_off[PERSONA:None]`

- **Warning fired**: True
- **Lines looked up**: L1001 → L1002
- **Write actions**: refuel_data(L1002)
- **Failed env assertions**: assert_can_send_mms, assert_data_refueling_amount
- **Missing actions**: grant_app_permission, refuel_data
- **Passed actions**: set_network_mode_preference, toggle_data, toggle_roaming
- **Refuel args used**: `{'customer_id': 'C1001', 'line_id': 'L1002', 'gb_amount': 0.1}`
- **Total tool calls**: 21

### Sim 90 (Task 1274): `[mms_issue]bad_wifi_calling|break_apn_mms_setting|data_mode_off|data_usage_exceeded|unseat_sim_card[PERSONA:None]`

- **Warning fired**: True
- **Lines looked up**: L1001 → L1002
- **Write actions**: refuel_data(L1002)
- **Failed env assertions**: assert_can_send_mms, assert_data_refueling_amount
- **Missing actions**: refuel_data
- **Passed actions**: toggle_wifi_calling, reset_apn_settings, reboot_device, toggle_data, reseat_sim_card
- **Refuel args used**: `{'customer_id': 'C1001', 'line_id': 'L1002', 'gb_amount': 0.1}`
- **Total tool calls**: 23

### Sim 95 (Task 1619): `[mms_issue]airplane_mode_on|bad_network_preference|break_app_both_permissions|data_usage_exceeded|unseat_sim_card|user_abroad_roaming_disabled_on[PERSONA:Hard]`

- **Warning fired**: True
- **Lines looked up**: L1001 → L1002
- **Write actions**: enable_roaming(L1002), refuel_data(L1002)
- **Failed env assertions**: assert_can_send_mms, assert_data_refueling_amount
- **Missing actions**: grant_app_permission, refuel_data
- **Passed actions**: toggle_airplane_mode, set_network_mode_preference, grant_app_permission, reseat_sim_card, enable_roaming
- **Refuel args used**: `{'customer_id': 'C1001', 'line_id': 'L1002', 'gb_amount': 1.0}`
- **Total tool calls**: 21

### Sim 100 (Task 1905): `[mms_issue]bad_network_preference|bad_wifi_calling|break_app_both_permissions|data_usage_exceeded|unseat_sim_card|user_abroad_roaming_disabled_off[PERSONA:None]`

- **Warning fired**: True
- **Lines looked up**: L1001 → L1002
- **Write actions**: enable_roaming(L1002), refuel_data(L1002)
- **Failed env assertions**: assert_can_send_mms, assert_data_refueling_amount
- **Missing actions**: refuel_data, toggle_roaming
- **Passed actions**: set_network_mode_preference, toggle_wifi_calling, grant_app_permission, grant_app_permission, reseat_sim_card, enable_roaming
- **Refuel args used**: `{'customer_id': 'C1001', 'line_id': 'L1002', 'gb_amount': 1.0}`
- **Total tool calls**: 29

### Sim 101 (Task 1953): `[mms_issue]bad_wifi_calling|break_apn_mms_setting|break_app_both_permissions|data_mode_off|data_usage_exceeded|user_abroad_roaming_disabled_off[PERSONA:None]`

- **Warning fired**: True
- **Lines looked up**: L1001 → L1002
- **Write actions**: enable_roaming(L1002), refuel_data(L1002)
- **Failed env assertions**: assert_can_send_mms, assert_data_refueling_amount
- **Missing actions**: refuel_data, toggle_roaming
- **Passed actions**: toggle_wifi_calling, reset_apn_settings, reboot_device, grant_app_permission, grant_app_permission, toggle_data, enable_roaming
- **Refuel args used**: `{'customer_id': 'C1001', 'line_id': 'L1002', 'gb_amount': 0.1}`
- **Total tool calls**: 28

### Sim 102 (Task 2228): `[mms_issue]airplane_mode_on|bad_network_preference|bad_wifi_calling|break_app_sms_permission|data_mode_off|data_usage_exceeded|unseat_sim_card|user_abroad_roaming_disabled_off[PERSONA:None]`

- **Warning fired**: True
- **Lines looked up**: L1001 → L1002
- **Write actions**: enable_roaming(L1002), refuel_data(L1002)
- **Failed env assertions**: assert_can_send_mms, assert_data_refueling_amount
- **Missing actions**: grant_app_permission, refuel_data, reseat_sim_card, toggle_roaming
- **Passed actions**: toggle_airplane_mode, set_network_mode_preference, toggle_wifi_calling, toggle_data, enable_roaming
- **Refuel args used**: `{'customer_id': 'C1001', 'line_id': 'L1002', 'gb_amount': 0.1}`
- **Total tool calls**: 17

### Sim 105 (Task 2238): `[mms_issue]airplane_mode_on|bad_network_preference|bad_wifi_calling|break_apn_mms_setting|break_app_storage_permission|data_mode_off|data_usage_exceeded|unseat_sim_card[PERSONA:Easy]`

- **Warning fired**: True
- **Lines looked up**: L1001 → L1002
- **Write actions**: refuel_data(L1002)
- **Failed env assertions**: assert_can_send_mms, assert_data_refueling_amount
- **Missing actions**: toggle_wifi_calling, refuel_data
- **Passed actions**: toggle_airplane_mode, set_network_mode_preference, reset_apn_settings, reboot_device, grant_app_permission, toggle_data, reseat_sim_card
- **Refuel args used**: `{'customer_id': 'C1001', 'line_id': 'L1002', 'gb_amount': 0.1}`
- **Total tool calls**: 21

### Sim 106 (Task 2279): `[mms_issue]airplane_mode_on|bad_network_preference|bad_wifi_calling|break_apn_mms_setting|break_app_sms_permission|data_mode_off|data_usage_exceeded|unseat_sim_card|user_abroad_roaming_disabled_on[PERSONA:None]`

- **Warning fired**: True
- **Lines looked up**: L1001 → L1002
- **Write actions**: enable_roaming(L1002), refuel_data(L1002)
- **Failed env assertions**: assert_can_send_mms, assert_data_refueling_amount
- **Missing actions**: toggle_wifi_calling, grant_app_permission, refuel_data
- **Passed actions**: toggle_airplane_mode, set_network_mode_preference, reset_apn_settings, reboot_device, toggle_data, reseat_sim_card, enable_roaming
- **Refuel args used**: `{'customer_id': 'C1001', 'line_id': 'L1002', 'gb_amount': 0.1}`
- **Total tool calls**: 24

### Sim 107 (Task 2280): `[mms_issue]airplane_mode_on|bad_network_preference|bad_wifi_calling|break_apn_mms_setting|break_app_storage_permission|data_mode_off|data_usage_exceeded|unseat_sim_card|user_abroad_roaming_disabled_on[PERSONA:Easy]`

- **Warning fired**: True
- **Lines looked up**: L1001 → L1002
- **Write actions**: enable_roaming(L1002), refuel_data(L1002)
- **Failed env assertions**: assert_can_send_mms, assert_data_refueling_amount
- **Missing actions**: toggle_wifi_calling, refuel_data
- **Passed actions**: toggle_airplane_mode, set_network_mode_preference, reset_apn_settings, reboot_device, grant_app_permission, toggle_data, reseat_sim_card, enable_roaming
- **Refuel args used**: `{'customer_id': 'C1001', 'line_id': 'L1002', 'gb_amount': 0.1}`
- **Total tool calls**: 22

### Sim 108 (Task 2276): `[mms_issue]airplane_mode_on|bad_network_preference|bad_wifi_calling|break_apn_mms_setting|break_app_sms_permission|data_mode_off|data_usage_exceeded|unseat_sim_card|user_abroad_roaming_enabled_off[PERSONA:None]`

- **Warning fired**: True
- **Lines looked up**: L1001 → L1002
- **Write actions**: refuel_data(L1002)
- **Failed env assertions**: assert_data_refueling_amount
- **Passed env assertions**: assert_can_send_mms
- **Missing actions**: refuel_data
- **Passed actions**: toggle_airplane_mode, set_network_mode_preference, toggle_wifi_calling, reset_apn_settings, reboot_device, grant_app_permission, toggle_data, reseat_sim_card, toggle_roaming
- **Refuel args used**: `{'customer_id': 'C1001', 'line_id': 'L1002', 'gb_amount': 0.1}`
- **Total tool calls**: 30

### Sim 110 (Task 2256): `[mms_issue]airplane_mode_on|bad_network_preference|bad_wifi_calling|break_apn_mms_setting|break_app_storage_permission|data_usage_exceeded|unseat_sim_card|user_abroad_roaming_disabled_off[PERSONA:Easy]`

- **Warning fired**: True
- **Lines looked up**: L1001 → L1002
- **Write actions**: enable_roaming(L1002), refuel_data(L1002)
- **Failed env assertions**: assert_can_send_mms, assert_data_refueling_amount
- **Missing actions**: refuel_data
- **Passed actions**: toggle_airplane_mode, set_network_mode_preference, toggle_wifi_calling, reset_apn_settings, reboot_device, grant_app_permission, reseat_sim_card, enable_roaming, toggle_roaming
- **Refuel args used**: `{'customer_id': 'C1001', 'line_id': 'L1002', 'gb_amount': 0.1}`
- **Total tool calls**: 29

### Sim 112 (Task 2281): `[mms_issue]airplane_mode_on|bad_network_preference|bad_wifi_calling|break_apn_mms_setting|break_app_both_permissions|data_mode_off|data_usage_exceeded|unseat_sim_card|user_abroad_roaming_disabled_on[PERSONA:Hard]`

- **Warning fired**: True
- **Lines looked up**: L1001 → L1002
- **Write actions**: enable_roaming(L1002), refuel_data(L1002)
- **Failed env assertions**: assert_can_send_mms, assert_data_refueling_amount
- **Missing actions**: toggle_wifi_calling, refuel_data
- **Passed actions**: toggle_airplane_mode, set_network_mode_preference, reset_apn_settings, reboot_device, grant_app_permission, grant_app_permission, toggle_data, reseat_sim_card, enable_roaming
- **Refuel args used**: `{'customer_id': 'C1001', 'line_id': 'L1002', 'gb_amount': 0.1}`
- **Total tool calls**: 28

## D. Never refueled (10 tasks)

> Agent should have called refuel_data but never did

### Sim 31 (Task 253): `[mobile_data_issue]airplane_mode_on|bad_network_preference|bad_vpn|data_mode_off|data_saver_mode_on|data_usage_exceeded|user_abroad_roaming_disabled_off[PERSONA:Hard]`

- **Warning fired**: True
- **Lines looked up**: L1001 → L1002
- **Write actions**: enable_roaming(L1002)
- **Failed env assertions**: assert_mobile_data_status, assert_internet_speed, assert_data_refueling_amount
- **Missing actions**: refuel_data
- **Passed actions**: toggle_airplane_mode, set_network_mode_preference, disconnect_vpn, toggle_data, toggle_data_saver_mode, enable_roaming, toggle_roaming
- **Total tool calls**: 17

### Sim 77 (Task 496): `[mms_issue]break_app_sms_permission|data_usage_exceeded|user_abroad_roaming_disabled_on[PERSONA:None]`

- **Warning fired**: True
- **Lines looked up**: L1001 → L1002
- **Write actions**: enable_roaming(L1002)
- **Failed env assertions**: assert_can_send_mms, assert_data_refueling_amount
- **Missing actions**: grant_app_permission, refuel_data
- **Passed actions**: enable_roaming
- **Total tool calls**: 4

### Sim 81 (Task 660): `[mms_issue]airplane_mode_on|bad_network_preference|break_apn_mms_setting|data_usage_exceeded[PERSONA:Hard]`

- **Warning fired**: False
- **Lines looked up**: none
- **Failed env assertions**: assert_can_send_mms, assert_data_refueling_amount
- **Missing actions**: refuel_data
- **Passed actions**: toggle_airplane_mode, set_network_mode_preference, reset_apn_settings, reboot_device
- **Total tool calls**: 16

### Sim 84 (Task 948): `[mms_issue]bad_wifi_calling|break_apn_mms_setting|break_app_sms_permission|data_usage_exceeded[PERSONA:Hard]`

- **Warning fired**: False
- **Lines looked up**: none
- **Failed env assertions**: assert_can_send_mms, assert_data_refueling_amount
- **Missing actions**: grant_app_permission, refuel_data
- **Passed actions**: toggle_wifi_calling, reset_apn_settings, reboot_device
- **Total tool calls**: 13

### Sim 91 (Task 1508): `[mms_issue]bad_network_preference|bad_wifi_calling|break_app_both_permissions|data_usage_exceeded|user_abroad_roaming_disabled_off[PERSONA:Hard]`

- **Warning fired**: True
- **Lines looked up**: L1001 → L1002
- **Write actions**: enable_roaming(L1002)
- **Failed env assertions**: assert_can_send_mms, assert_data_refueling_amount
- **Missing actions**: grant_app_permission, refuel_data
- **Passed actions**: set_network_mode_preference, toggle_wifi_calling, grant_app_permission, enable_roaming, toggle_roaming
- **Total tool calls**: 23

### Sim 92 (Task 1615): `[mms_issue]airplane_mode_on|bad_network_preference|bad_wifi_calling|data_usage_exceeded|unseat_sim_card|user_abroad_roaming_disabled_on[PERSONA:Easy]`

- **Warning fired**: True
- **Lines looked up**: L1001 → L1002
- **Write actions**: enable_roaming(L1002)
- **Failed env assertions**: assert_can_send_mms, assert_data_refueling_amount
- **Missing actions**: toggle_wifi_calling, refuel_data, reseat_sim_card
- **Passed actions**: toggle_airplane_mode, set_network_mode_preference, enable_roaming
- **Total tool calls**: 17

### Sim 97 (Task 2102): `[mms_issue]airplane_mode_on|bad_network_preference|break_apn_mms_setting|break_app_both_permissions|data_mode_off|data_usage_exceeded|user_abroad_roaming_enabled_off[PERSONA:None]`

- **Warning fired**: True
- **Lines looked up**: L1001 → L1002
- **Failed env assertions**: assert_can_send_mms, assert_data_refueling_amount
- **Missing actions**: grant_app_permission, refuel_data, toggle_roaming
- **Passed actions**: toggle_airplane_mode, set_network_mode_preference, reset_apn_settings, reboot_device, grant_app_permission, toggle_data
- **Total tool calls**: 12

### Sim 98 (Task 1983): `[mms_issue]airplane_mode_on|bad_wifi_calling|break_app_both_permissions|data_mode_off|data_usage_exceeded|unseat_sim_card|user_abroad_roaming_enabled_off[PERSONA:None]`

- **Warning fired**: True
- **Lines looked up**: L1001 → L1002
- **Failed env assertions**: assert_can_send_mms, assert_data_refueling_amount
- **Missing actions**: refuel_data
- **Passed actions**: toggle_airplane_mode, toggle_wifi_calling, grant_app_permission, grant_app_permission, toggle_data, reseat_sim_card, toggle_roaming
- **Total tool calls**: 24

### Sim 104 (Task 2148): `[mms_issue]bad_network_preference|bad_wifi_calling|break_app_sms_permission|data_mode_off|data_usage_exceeded|unseat_sim_card|user_abroad_roaming_enabled_off[PERSONA:Easy]`

- **Warning fired**: True
- **Lines looked up**: L1001 → L1002
- **Failed env assertions**: assert_can_send_mms, assert_data_refueling_amount
- **Missing actions**: grant_app_permission, refuel_data
- **Passed actions**: set_network_mode_preference, toggle_wifi_calling, toggle_data, reseat_sim_card, toggle_roaming
- **Total tool calls**: 20

### Sim 113 (Task 2284): `[mms_issue]airplane_mode_on|bad_network_preference|bad_wifi_calling|break_apn_mms_setting|break_app_both_permissions|data_mode_off|data_usage_exceeded|unseat_sim_card|user_abroad_roaming_disabled_off[PERSONA:Hard]`

- **Warning fired**: True
- **Lines looked up**: L1001 → L1002
- **Write actions**: enable_roaming(L1002)
- **Failed env assertions**: assert_can_send_mms, assert_data_refueling_amount
- **Missing actions**: toggle_wifi_calling, refuel_data, toggle_roaming
- **Passed actions**: toggle_airplane_mode, set_network_mode_preference, reset_apn_settings, reboot_device, grant_app_permission, grant_app_permission, toggle_data, reseat_sim_card, enable_roaming
- **Total tool calls**: 23

## E. Missed troubleshooting step (13 tasks)

> Agent missed a required user-side troubleshooting action

### Sim 4 (Task 17): `[mobile_data_issue]data_saver_mode_on|user_abroad_roaming_enabled_off[PERSONA:Easy]`

- **Warning fired**: True
- **Lines looked up**: L1001 → L1002
- **Failed env assertions**: assert_internet_speed
- **Passed env assertions**: assert_mobile_data_status
- **Missing actions**: toggle_data_saver_mode
- **Passed actions**: toggle_roaming
- **Total tool calls**: 6

### Sim 10 (Task 83): `[mobile_data_issue]bad_network_preference|bad_vpn|user_abroad_roaming_disabled_on[PERSONA:None]`

- **Warning fired**: True
- **Lines looked up**: L1001 → L1002
- **Write actions**: enable_roaming(L1002)
- **Failed env assertions**: assert_internet_speed
- **Passed env assertions**: assert_mobile_data_status
- **Missing actions**: disconnect_vpn
- **Passed actions**: set_network_mode_preference, enable_roaming
- **Total tool calls**: 8

### Sim 11 (Task 73): `[mobile_data_issue]bad_network_preference|bad_vpn|user_abroad_roaming_enabled_off[PERSONA:Easy]`

- **Warning fired**: True
- **Lines looked up**: L1001 → L1002
- **Failed env assertions**: assert_internet_speed
- **Passed env assertions**: assert_mobile_data_status
- **Missing actions**: disconnect_vpn
- **Passed actions**: set_network_mode_preference, toggle_roaming
- **Total tool calls**: 8

### Sim 12 (Task 93): `[mobile_data_issue]bad_network_preference|bad_vpn|user_abroad_roaming_disabled_off[PERSONA:Hard]`

- **Warning fired**: True
- **Lines looked up**: L1001 → L1002
- **Write actions**: enable_roaming(L1002)
- **Failed env assertions**: assert_internet_speed
- **Passed env assertions**: assert_mobile_data_status
- **Missing actions**: disconnect_vpn
- **Passed actions**: set_network_mode_preference, enable_roaming, toggle_roaming
- **Total tool calls**: 8

### Sim 15 (Task 136): `[mobile_data_issue]airplane_mode_on|bad_network_preference|data_mode_off|data_saver_mode_on[PERSONA:Hard]`

- **Warning fired**: False
- **Lines looked up**: none
- **Failed env assertions**: assert_internet_speed
- **Passed env assertions**: assert_mobile_data_status
- **Missing actions**: toggle_data_saver_mode
- **Passed actions**: toggle_airplane_mode, set_network_mode_preference, toggle_data
- **Total tool calls**: 7

### Sim 24 (Task 197): `[mobile_data_issue]airplane_mode_on|bad_network_preference|bad_vpn|data_saver_mode_on|user_abroad_roaming_disabled_on[PERSONA:Easy]`

- **Warning fired**: True
- **Lines looked up**: L1001 → L1002
- **Write actions**: enable_roaming(L1002)
- **Failed env assertions**: assert_internet_speed
- **Passed env assertions**: assert_mobile_data_status
- **Missing actions**: toggle_data_saver_mode
- **Passed actions**: toggle_airplane_mode, set_network_mode_preference, disconnect_vpn, enable_roaming
- **Total tool calls**: 9

### Sim 25 (Task 230): `[mobile_data_issue]bad_network_preference|bad_vpn|data_saver_mode_on|data_usage_exceeded|user_abroad_roaming_disabled_off[PERSONA:Easy]`

- **Warning fired**: True
- **Lines looked up**: L1001 → L1002
- **Write actions**: enable_roaming(L1002), refuel_data(L1002)
- **Failed env assertions**: assert_internet_speed
- **Passed env assertions**: assert_mobile_data_status, assert_data_refueling_amount
- **Missing actions**: disconnect_vpn
- **Passed actions**: set_network_mode_preference, toggle_data_saver_mode, refuel_data, enable_roaming, toggle_roaming
- **Total tool calls**: 15

### Sim 27 (Task 238): `[mobile_data_issue]airplane_mode_on|bad_network_preference|data_mode_off|data_saver_mode_on|data_usage_exceeded|user_abroad_roaming_disabled_on[PERSONA:None]`

- **Warning fired**: True
- **Lines looked up**: L1001 → L1002
- **Write actions**: enable_roaming(L1002), refuel_data(L1002)
- **Failed env assertions**: assert_internet_speed
- **Passed env assertions**: assert_mobile_data_status, assert_data_refueling_amount
- **Missing actions**: toggle_data_saver_mode
- **Passed actions**: toggle_airplane_mode, set_network_mode_preference, toggle_data, refuel_data, enable_roaming
- **Total tool calls**: 12

### Sim 79 (Task 531): `[mms_issue]bad_network_preference|break_app_sms_permission|user_abroad_roaming_disabled_on[PERSONA:Hard]`

- **Warning fired**: True
- **Lines looked up**: L1001 → L1002
- **Write actions**: enable_roaming(L1002)
- **Failed env assertions**: assert_can_send_mms
- **Missing actions**: grant_app_permission
- **Passed actions**: set_network_mode_preference, enable_roaming
- **Total tool calls**: 14

### Sim 83 (Task 788): `[mms_issue]bad_wifi_calling|break_apn_mms_setting|unseat_sim_card|user_abroad_roaming_enabled_off[PERSONA:Easy]`

- **Warning fired**: True
- **Lines looked up**: L1001 → L1002
- **Failed env assertions**: assert_can_send_mms
- **Missing actions**: toggle_wifi_calling
- **Passed actions**: reset_apn_settings, reboot_device, reseat_sim_card, toggle_roaming
- **Total tool calls**: 17

### Sim 87 (Task 1088): `[mms_issue]airplane_mode_on|bad_network_preference|bad_wifi_calling|break_app_storage_permission|unseat_sim_card[PERSONA:Hard]`

- **Warning fired**: True
- **Lines looked up**: L1001 → L1002
- **Failed env assertions**: assert_can_send_mms
- **Missing actions**: toggle_wifi_calling
- **Passed actions**: toggle_airplane_mode, set_network_mode_preference, grant_app_permission, reseat_sim_card
- **Total tool calls**: 20

### Sim 99 (Task 2089): `[mms_issue]airplane_mode_on|bad_network_preference|bad_wifi_calling|break_apn_mms_setting|break_app_both_permissions|unseat_sim_card|user_abroad_roaming_enabled_off[PERSONA:Hard]`

- **Warning fired**: True
- **Lines looked up**: L1001 → L1002
- **Failed env assertions**: assert_can_send_mms
- **Missing actions**: toggle_wifi_calling, grant_app_permission
- **Passed actions**: toggle_airplane_mode, set_network_mode_preference, reset_apn_settings, reboot_device, grant_app_permission, reseat_sim_card, toggle_roaming
- **Total tool calls**: 19

### Sim 109 (Task 2178): `[mms_issue]bad_network_preference|bad_wifi_calling|break_apn_mms_setting|break_app_storage_permission|data_mode_off|data_usage_exceeded|unseat_sim_card[PERSONA:Easy]`

- **Warning fired**: True
- **Lines looked up**: L1001 → L1002
- **Write actions**: refuel_data(L1002)
- **Failed env assertions**: assert_can_send_mms
- **Passed env assertions**: assert_data_refueling_amount
- **Missing actions**: toggle_wifi_calling
- **Passed actions**: set_network_mode_preference, reset_apn_settings, reboot_device, grant_app_permission, toggle_data, refuel_data, reseat_sim_card
- **Total tool calls**: 44

## F. Missed user action (2 tasks)

> Agent missed a required user action (toggle_roaming, reseat_sim, etc.)

### Sim 44 (Task 275): `[service_issue]airplane_mode_on|break_apn_settings|unseat_sim_card[PERSONA:None]`

- **Warning fired**: True
- **Lines looked up**: L1001 → L1002
- **Failed env assertions**: assert_service_status
- **Passed env assertions**: assert_no_overdue_bill
- **Missing actions**: reset_apn_settings, reboot_device
- **Passed actions**: toggle_airplane_mode, reseat_sim_card
- **Total tool calls**: 12

### Sim 70 (Task 343): `[mms_issue]bad_network_preference|user_abroad_roaming_disabled_off[PERSONA:None]`

- **Warning fired**: True
- **Lines looked up**: L1001 → L1002
- **Write actions**: enable_roaming(L1002)
- **Failed env assertions**: assert_can_send_mms
- **Missing actions**: toggle_roaming
- **Passed actions**: set_network_mode_preference, enable_roaming
- **Total tool calls**: 18

## G. Missed transfer (1 tasks)

> Agent should have transferred to human agent but did not

### Sim 61 (Task 299): `[service_issue]airplane_mode_on|break_apn_settings|lock_sim_card_pin|overdue_bill_suspension|unseat_sim_card[PERSONA:None]`

- **Warning fired**: False
- **Lines looked up**: L1002
- **Write actions**: resume_line(L1002)
- **Passed env assertions**: assert_service_status
- **Missing actions**: transfer_to_human_agents
- **Total tool calls**: 7

## H. Other/environment (2 tasks)

> Task failed for other reasons (env state not resolved despite correct actions)

### Sim 29 (Task 242): `[mobile_data_issue]airplane_mode_on|bad_network_preference|bad_vpn|data_mode_off|data_saver_mode_on|user_abroad_roaming_disabled_off[PERSONA:Hard]`

- **Warning fired**: True
- **Lines looked up**: L1001 → L1002
- **Write actions**: enable_roaming(L1002)
- **Failed env assertions**: assert_mobile_data_status, assert_internet_speed
- **Passed actions**: toggle_airplane_mode, set_network_mode_preference, disconnect_vpn, toggle_data, toggle_data_saver_mode, enable_roaming, toggle_roaming
- **Total tool calls**: 27

### Sim 64 (Task 293): `[service_issue]airplane_mode_on|break_apn_settings|overdue_bill_suspension|unseat_sim_card[PERSONA:None]`

- **Warning fired**: False
- **Lines looked up**: none
- **Write actions**: resume_line(L1002)
- **Total tool calls**: 294

## Comparison with Previous Runs

| Run | Reward | ENV_ASSERTION | ACTION | Wrong-Line |
|-----|--------|---------------|--------|------------|
| Baseline CoT (no verifier) | 32.0% | 35.0% | 76.0% | 62/66 failures |
| Verifier v1 (no line warning) | 42.1% | 43.4% | 95.0% | 62/66 failures |
| **Verifier v2 (line warning)** | **52.6%** | **56.0%** | **95.0%** | **4/54 failures** |

## Key Insights

1. **Line-phone warning eliminated most wrong-line errors**: Down from 62 to 4 (94% reduction)
2. **Refueling is now the #1 issue**: 27/54 failures (17 wrong amount + 10 never done)
   - Agent consistently uses `gb_amount=0.1` instead of `2.0` from the ticket
3. **Infinite loop bug**: 5 tasks where agent keeps cycling between L1001 and L1002
   - Warning fires every time L1001 is looked up, but agent forgets and retries
   - Fix: Only fire warning once per line, or suppress after first correction
4. **Missed troubleshooting steps**: 14 occurrences across 4 action types
   - `disconnect_vpn` (4), `toggle_data_saver_mode` (4), `toggle_wifi_calling` (4), `grant_app_permission` (2)
5. **3 of 4 wrong-line writes happened despite warning**: Agent ignored the feedback in complex MMS tasks

## Recommended Next Steps

1. **Fix refuel amount**: Add a verifier rule or post-exec check for `refuel_data` that compares `gb_amount` against the ticket
2. **Fix loop bug**: Track which lines have already been warned about; suppress duplicate warnings
3. **Block wrong-line writes**: Pre-execution rule that blocks `enable_roaming(L1001)` when user phone is known to be on L1002
4. **Improve troubleshooting coverage**: The agent misses VPN, data saver, wifi calling, and app permission steps