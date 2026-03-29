"""Check if verifier SHOULD have blocked writes in failing tasks."""
import json
import sys
import types
sys.modules['audioop'] = types.ModuleType('audioop')

from tau2.verifier.verifier import _load_spec_from_generated_json

verifier_path = 'data/simulations/20260328_152553_airline_llm_agent_Qwen3-30B-A3B-Thinking-2507_user_simulator_Qwen3-30B-A3B-Thinking-2507/results.json'
with open(verifier_path) as f:
    data = json.load(f)

write_tools = {'book_reservation', 'cancel_reservation', 'update_reservation_flights',
               'update_reservation_baggages', 'update_reservation_passengers', 'send_certificate',
               'transfer_to_human_agents'}

print("FAILING TASKS (reward=0) with WRITE calls in verifier run #12:")
print("=" * 70)
for sim in data['simulations']:
    tid = sim['task_id']
    ri = sim.get('reward_info') or {}
    reward = ri.get('reward', None)
    if reward is None or reward != 0:
        continue
    
    writes = []
    for msg in sim.get('messages', []):
        if isinstance(msg, dict) and msg.get('role') == 'assistant' and msg.get('tool_calls'):
            for tc in msg['tool_calls']:
                if tc.get('name') in write_tools:
                    writes.append((tc['name'], tc.get('arguments', {})))
    
    if not writes:
        continue
    
    # Load the spec for this task
    spec = _load_spec_from_generated_json(str(tid), 'airline')
    if spec is None:
        print(f"Task {tid}: NO SPEC!")
        continue
    
    print(f"\nTask {tid} (reward=0):")
    print(f"  Spec forbidden: {spec.forbidden_write_tools}")
    print(f"  Spec allowed:   {[a.tool_name for a in spec.allowed_write_actions]}")
    print(f"  Spec max_writes: {spec.max_write_calls}")
    for tool_name, args in writes:
        would_block = tool_name in spec.forbidden_write_tools
        in_allowed = any(a.tool_name == tool_name for a in spec.allowed_write_actions)
        max_exceeded = spec.max_write_calls is not None and spec.max_write_calls == 0
        print(f"  WRITE: {tool_name} → forbidden={would_block}, in_allowed={in_allowed}, max_exceeded={max_exceeded}")
