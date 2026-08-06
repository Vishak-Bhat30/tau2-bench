#!/usr/bin/env bash
# Run retail tau2-bench with GPT-5.6 Sol as the sole tool-call verifier.
set -euo pipefail

cd "$(dirname "$0")"

# Agent and user/judge endpoints.
export OPENAI_API_BASE=http://127.0.0.1:3141/v1
export OPENAI_BASE_URL=http://127.0.0.1:3141/v1
export OPENAI_API_KEY=dummy

# Select the LLM verifier instead of formal policy/trace rules.
export TAU2_VERIFIER=1
export TAU2_VERIFIER_MODE=llm
export TAU2_LLM_VERIFIER_API_BASE=http://127.0.0.1:3141/v1
export TAU2_LLM_VERIFIER_API_KEY=dummy
export TAU2_LLM_VERIFIER_MODEL=gpt-5.6-sol
export TAU2_LLM_VERIFIER_FAIL_CLOSED="${TAU2_LLM_VERIFIER_FAIL_CLOSED:-0}"
export TAU2_LLM_VERIFIER_MAX_TOKENS="${TAU2_LLM_VERIFIER_MAX_TOKENS:-500}"

NUM_TASKS="${NUM_TASKS:-114}"
NUM_TRIALS="${NUM_TRIALS:-1}"

for port in 8000 3141; do
  if curl -sf "http://localhost:${port}/v1/models" >/dev/null 2>&1; then
    echo "[preflight] OpenAI-compatible server on :${port} is up."
  else
    echo "[preflight] WARNING: nothing answered on :${port}/v1/models."
  fi
done

echo "[config] Verifier: ${TAU2_LLM_VERIFIER_MODEL} at ${TAU2_LLM_VERIFIER_API_BASE}"
echo "[config] Tasks: ${NUM_TASKS}; trials: ${NUM_TRIALS}"

uv run tau2 run \
    --domain retail \
    --agent llm_agent \
    --user user_simulator \
    --agent-llm openai/Qwen/Qwen3-30B-A3B-Thinking-2507 \
    --agent-llm-args '{"temperature": 0.6, "top_p": 0.95, "top_k": 20, "api_base": "http://localhost:8000/v1"}' \
    --user-llm openai/gpt-4o-mini \
    --user-llm-args '{"api_base": "http://127.0.0.1:3141/v1", "api_key": "dummy"}' \
    --num-trials "$NUM_TRIALS" \
    --num-tasks "$NUM_TASKS" \
    --enable-tool-call-verifier