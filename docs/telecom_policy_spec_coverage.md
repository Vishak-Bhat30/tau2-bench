# Telecom Policy Spec — Coverage Map

This document maps every policy statement in `main_policy_solo.md` and `tech_support_workflow_solo.md` to its corresponding verifier rule(s) in `telecom_policy_spec.py`.

---

## Part 1: Policy Line → Rule Mapping

### General Agent Behavior

| Policy Statement | Rule | Type |
|---|---|---|
| "You should only make one tool call at a time." | *Enforced by framework* | N/A |
| "You should deny user requests that are against this policy." | All rules collectively | — |
| "You should escalate to a human agent if and only if the request cannot be handled within the scope of your actions." | `rule_transfer_only_when_needed` | SLM |
| "You should try your best to resolve the issue before escalating." | `rule_transfer_only_when_needed` | SLM |

### Customer Lookup

| Policy Statement | Rule | Type |
|---|---|---|
| "You can look up customer information using: Phone number, Customer ID, Full name with date of birth" | — (read-only tools, no policy check needed) | N/A |
| "For name lookup, date of birth is required for verification purposes." | `rule_customer_lookup_name_requires_dob` | Cheap (DB) |

### Overdue Bill Payment

| Policy Statement | Rule | Type |
|---|---|---|
| "Check the bill status to make sure it is overdue." | `rule_payment_bill_must_be_overdue` | Cheap (DB) |
| "Check the bill amount due" | *Informational step — no tool-call constraint* | N/A |
| "Send the user a payment request for the overdue bill." | `rule_payment_bill_must_be_overdue` | Cheap (DB) |
| "If the ticket specifies that the user has given you the permission to make payments, you can: check_payment_request / make_payment" | *Solo-mode flow — permission is in ticket context* | N/A |
| "Check that the bill status is updated to PAID." | *Post-action verification step — no tool arg to check* | N/A |
| "A user can only have one bill in the AWAITING PAYMENT status at a time." | `rule_payment_no_duplicate_awaiting` | Cheap (DB) |
| "The send payment request tool will not check if the bill is overdue. You should always check that the bill is overdue before sending a payment request." | `rule_payment_bill_must_be_overdue` | Cheap (DB) |
| Verify payment targets the correct bill discussed in conversation | `rule_arg_payment_bill` | SLM |

### Line Suspension

| Policy Statement | Rule | Type |
|---|---|---|
| "A line can be suspended for: overdue bill, contract end date in the past." | `rule_suspend_valid_reason` | SLM |
| "You are allowed to lift the suspension after the user has paid all their overdue bills." | `rule_resume_all_bills_paid` | Cheap (DB) |
| "You are not allowed to lift the suspension if the line's contract end date is in the past." | `rule_resume_contract_not_expired` | Cheap (DB) |
| "After you resume the line, the user will have to reboot their device to get service." | *Informational — agent must tell user, not a tool arg* | N/A |
| Verify resume_line targets the correct line/customer | `rule_arg_resume_line` | SLM |

### Data Refueling

| Policy Statement | Rule | Type |
|---|---|---|
| "The maximum amount of data that can be refueled is 2GB." | `rule_refuel_max_2gb` | Cheap (DB) |
| Line must be active to refuel | `rule_refuel_line_active` | Cheap (DB) |
| "Know how much data they want to refuel" | *Conversational flow — not a tool arg constraint* | N/A |
| "Confirm the price" | *Conversational flow — not a tool arg constraint* | N/A |
| "Apply the refueled data to the line associated with the phone number the user provided." | `rule_arg_refuel_line` | SLM |
| Only refuel when data usage actually exceeds the limit (tech support context) | `rule_refuel_only_when_data_exceeded` | SLM |

### Change Plan

| Policy Statement | Rule | Type |
|---|---|---|
| "Make sure you know what line the user wants to change the plan for." | *No `change_plan` tool exists in the codebase — plans are read-only* | N/A |
| "Gather available plans / Find plans compatible" | *Read-only operation — `get_available_plan_ids`* | N/A |
| "Apply the plan to the line" | *No write tool for plan changes exists* | N/A |

> **Note**: There is no `change_plan` write tool in `tools.py`. The policy section exists but the tool is not implemented, so no verifier rule is needed.

### Data Roaming

| Policy Statement | Rule | Type |
|---|---|---|
| "If a user is traveling outside their home network, you should check if the line is roaming enabled." | *Read-only check — no constraint* | N/A |
| "If it is not, you should enable it at no cost for the user." | — (enabling roaming is always allowed) | N/A |
| Should not disable roaming while user is traveling | `rule_disable_roaming_not_while_traveling` | SLM |
| Verify enable_roaming targets the correct line/customer | `rule_arg_enable_roaming_line` | SLM |

### Technical Support (from `tech_support_workflow_solo.md`)

| Policy / Workflow Statement | Rule | Type |
|---|---|---|
| Path 1 (No Service): Airplane mode, SIM, APN reset, reboot, line suspension checks | Resume/suspend rules cover line-related actions; device actions are user-side tools not policy-checked | — |
| Step 1.2: "If SIM is LOCKED with PIN/PUK — Escalate to technical support" | `rule_transfer_only_when_needed` (SIM lock is a valid reason) | SLM |
| Step 1.4: Line suspension → follow main policy | `rule_resume_contract_not_expired`, `rule_resume_all_bills_paid` | Cheap (DB) |
| Path 2.1 (Unavailable Data): Service check → roaming → mobile data → data usage | Roaming rules + refuel rules cover the actionable tool calls | — |
| Step 2.1.2: Enable roaming at no cost for traveling users | `rule_disable_roaming_not_while_traveling`, `rule_arg_enable_roaming_line` | SLM |
| Step 2.1.4: Data exceeded → refuel or change plan | `rule_refuel_max_2gb`, `rule_refuel_line_active`, `rule_refuel_only_when_data_exceeded` | Mixed |
| Path 2.2 (Slow Data): Data saver, network mode, VPN | *Device-side toggle actions — no policy constraints on these* | N/A |
| Path 3 (MMS): Service → data → network tech → Wi-Fi calling → permissions → APN | *Device-side diagnostic/fix actions — no policy constraints* | N/A |
| "Make sure you try all the relevant resolution steps before transferring" | `rule_transfer_only_when_needed` | SLM |

---

## Part 2: Tool Call → Rule Mapping

### Agent-Side Write Tools

| Tool | Rules Applied | Description |
|---|---|---|
| `suspend_line` | `rule_suspend_valid_reason` | Reason must be overdue bill or expired contract |
| `resume_line` | `rule_resume_contract_not_expired`, `rule_resume_all_bills_paid`, `rule_arg_resume_line` | Contract not expired, all bills paid, correct line |
| `send_payment_request` | `rule_payment_bill_must_be_overdue`, `rule_payment_no_duplicate_awaiting`, `rule_arg_payment_bill` | Bill must be overdue, no duplicate awaiting, correct bill |
| `refuel_data` | `rule_refuel_max_2gb`, `rule_refuel_line_active`, `rule_refuel_only_when_data_exceeded`, `rule_arg_refuel_line` | Max 2GB, line active, data exceeded, correct line |
| `enable_roaming` | `rule_arg_enable_roaming_line` | Correct line/customer |
| `disable_roaming` | `rule_disable_roaming_not_while_traveling` | Don't disable while user is traveling |
| `transfer_to_human_agents` | `rule_transfer_only_when_needed` | Only when request can't be handled by tools |

### Agent-Side Read Tools (no policy checks)

| Tool | Rules Applied |
|---|---|
| `get_customer_by_phone` | — |
| `get_customer_by_id` | — |
| `get_customer_by_name` | `rule_customer_lookup_name_requires_dob` |
| `get_details_by_id` | — |
| `get_bills_for_customer` | — |
| `get_data_usage` | — |

### User-Side Tools (device actions — no policy spec rules)

| Tool | Notes |
|---|---|
| `toggle_airplane_mode` | Tech support action — no policy constraint |
| `toggle_data` | Tech support action |
| `toggle_roaming` | Tech support action (device-side toggle) |
| `toggle_data_saver_mode` | Tech support action |
| `set_network_mode_preference` | Tech support action |
| `disconnect_vpn` / `connect_vpn` | Tech support action |
| `reseat_sim_card` | Tech support action |
| `reset_apn_settings` / `set_apn_settings` | Tech support action |
| `toggle_wifi` | Tech support action |
| `toggle_wifi_calling` | Tech support action |
| `grant_app_permission` | Tech support action |
| `reboot_device` | Tech support action |
| `check_status_bar` | Diagnostic (read-only) |
| `check_network_status` | Diagnostic (read-only) |
| `check_network_mode_preference` | Diagnostic (read-only) |
| `check_sim_status` | Diagnostic (read-only) |
| `check_data_restriction_status` | Diagnostic (read-only) |
| `check_apn_settings` | Diagnostic (read-only) |
| `check_wifi_status` | Diagnostic (read-only) |
| `check_wifi_calling_status` | Diagnostic (read-only) |
| `check_vpn_status` | Diagnostic (read-only) |
| `check_installed_apps` | Diagnostic (read-only) |
| `check_app_status` | Diagnostic (read-only) |
| `check_app_permissions` | Diagnostic (read-only) |
| `run_speed_test` | Diagnostic (read-only) |
| `can_send_mms` | Diagnostic (read-only) |
| `check_payment_request` | Payment flow (read-only) |
| `make_payment` | Payment flow (user-side write) |

---

## Part 3: Summary

| Category | Count |
|---|---|
| **Total rules** | 15 |
| **Cheap (DB-only) rules** | 7 |
| **SLM-based rules** | 8 |
| **Agent write tools covered** | 7/7 (100%) |
| **Agent read tools covered** | 1/6 (`get_customer_by_name`) |
| **Policy statements with rules** | 17 |
| **Policy statements — behavioral/conversational (no tool arg)** | 6 |
| **Policy statements — framework-enforced** | 1 |
| **Policy section with no tool implemented** | Change Plan (no write tool exists) |
