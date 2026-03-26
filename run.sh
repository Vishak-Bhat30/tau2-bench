tau2 run --domain airline \
  --agent-llm openai/Qwen/Qwen3-30B-A3B-Thinking-2507 \
  --agent-llm-args '{"temperature": 0.6, "top_p": 0.95, "top_k": 20}' \
  --user-llm openai/Qwen/Qwen3-30B-A3B-Thinking-2507 \
  --user-llm-args '{"temperature": 0.6, "top_p": 0.95, "top_k": 20}' \
  --num-trials 4 --num-tasks 50


tau2 run --domain retail \
  --agent-llm openai/Qwen/Qwen3-30B-A3B-Thinking-2507 \
  --agent-llm-args '{"temperature": 0.6, "top_p": 0.95, "top_k": 20}' \
  --user-llm openai/Qwen/Qwen3-30B-A3B-Thinking-2507 \
  --user-llm-args '{"temperature": 0.6, "top_p": 0.95, "top_k": 20}' \
  --num-trials 4 --num-tasks 114


tau2 run --domain telecom \
  --agent-llm openai/Qwen/Qwen3-30B-A3B-Thinking-2507 \
  --agent-llm-args '{"temperature": 0.6, "top_p": 0.95, "top_k": 20}' \
  --user-llm openai/Qwen/Qwen3-30B-A3B-Thinking-2507 \
  --user-llm-args '{"temperature": 0.6, "top_p": 0.95, "top_k": 20}' \
  --num-trials 4 --num-tasks 114