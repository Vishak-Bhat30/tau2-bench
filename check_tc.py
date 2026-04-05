import json
from collections import Counter

with open('data/simulations/20260329_082605_airline_llm_agent_Qwen3-30B-A3B-Thinking-2507_user_simulator_Qwen3-30B-A3B-Thinking-2507/results.json') as f:
    data = json.load(f)

WRITE_TOOLS = {'update_reservation_passengers', 'update_reservation_flights',
    'update_reservation_baggages', 'cancel_reservation', 'book_reservation',
    'send_certificate', 'transfer_to_human_agents'}

# For each failed task, show tool calls
for sim in data['simulations']:
    ri = sim['reward_info']
    reward = ri.get('reward', 0)
    if reward >= 1.0:
        continue
    
    calls = []
    for m in sim['messages']:
        if m.get('role') == 'assistant':
            for tc in (m.get('tool_calls') or []):
                name = tc.get('name', '')
                calls.append(name)
    
    writes = [c for c in calls if c in WRITE_TOOLS]
    call_counts = Counter(calls)
    
    bd = ri.get('reward_breakdown', {})
    v_count = sum(1 for m in sim['messages'] if isinstance(m.get('content',''), str) and '[VERIFIER]' in (m.get('content','') or ''))
    
    print(f"Task {sim['task_id']}: r={reward:.2f} bd={bd} v={v_count}")
    print(f"  Calls ({len(calls)}): {call_counts.most_common(5)}")
    if writes:
        print(f"  Writes: {writes}")
    else:
        print(f"  NO WRITES MADE")
    print()
