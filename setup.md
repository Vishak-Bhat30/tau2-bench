# Environment Setup Notes

## 1. Install System Dependencies (Ubuntu)

```bash
sudo apt-get update && sudo apt-get install -y portaudio19-dev ffmpeg
```

- `portaudio19-dev` — provides `portaudio.h`, required by the `pyaudio` Python package (used by the `voice` extra).
- `ffmpeg` — audio/video processing tool, also needed by voice features.

## 2. Install Python Dependencies

```bash
uv sync --all-extras
```

## 3. Activate the Virtual Environment

```bash
source .venv/bin/activate
```

## 4. Set Environment Variables for vLLM Server

The vLLM server exposes an OpenAI-compatible API. Tell LiteLLM to route to it:

```bash
export OPENAI_API_KEY="dummy"
export OPENAI_API_BASE="http://localhost:8000/v1"
```

You can put these in a `.env` file (copied from `.env.example`) for persistence.

## 5. Launch the vLLM Server

```bash
python -m vllm.entrypoints.openai.api_server \
  --model Qwen/Qwen3-30B-A3B-Thinking-2507 \
  --port 8000 \
  --tensor-parallel-size 8 \
  --enable-auto-tool-choice \
  --tool-call-parser hermes
```

Key flags:
- `--enable-auto-tool-choice` — enables the model to make function/tool calls
- `--tool-call-parser hermes` — uses the Hermes tool-call format parser for Qwen3

## 6. Run the Experiment

```bash
tau2 run --domain airline \
  --agent-llm openai/Qwen/Qwen3-30B-A3B-Thinking-2507 \
  --agent-llm-args '{"temperature": 0.6, "top_p": 0.95, "top_k": 20}' \
  --user-llm openai/Qwen/Qwen3-30B-A3B-Thinking-2507 \
  --user-llm-args '{"temperature": 0.6, "top_p": 0.95, "top_k": 20}' \
  --num-trials 1 --num-tasks 1
```

The `openai/` prefix tells LiteLLM to use the OpenAI-compatible protocol, which routes
to whatever `OPENAI_API_BASE` points at (i.e., your vLLM server on port 8000).

## 7. View Results

```bash
tau2 view
```

---

## Code Changes Made

### A. Thinking Trace Stripping (`<think>...</think>`)

Qwen3-Thinking wraps its internal reasoning in `<think>...</think>` tags. Stripping is
done **only at display time** (in `tau2 view`), NOT in `generate()`. The full thinking
trace is preserved in stored messages so the model retains its reasoning context during
the conversation.

**`src/tau2/utils/display.py` — line 717–719** (in message display loop)
```python
# Strip <think>...</think> blocks from thinking models
if raw_content:
    raw_content = re.sub(r"<think>.*?</think>", "", raw_content, flags=re.DOTALL).strip()
```

**To show reasoning traces in `tau2 view`**, comment out `src/tau2/utils/display.py` lines **717–719**.

### B. Reasoning Token Tracking

Added `reasoning_tokens` tracking from `completion_tokens_details` (reported by vLLM for thinking models):

**`src/tau2/utils/llm_utils.py` — `get_response_usage()` (line ~134)**
Now extracts `reasoning_tokens` from `usage.completion_tokens_details` if available.

**`src/tau2/utils/llm_utils.py` — `get_token_usage()` (line ~500)**
Now aggregates `reasoning_tokens` alongside prompt/completion tokens.

### C. Average Token Usage in `tau2 view`

Added per-conversation averages for prompt, completion, reasoning, and total tokens:

**`src/tau2/metrics/agent_metrics.py`** — Added fields:
- `avg_prompt_tokens`, `avg_completion_tokens`, `avg_reasoning_tokens`, `avg_total_tokens`
- Computed in `compute_metrics()` by iterating simulation messages.

**`src/tau2/utils/display.py`** — Added "Token Usage (Avg/Conversation)" section
in the metrics table, shown right after "Avg Cost/Conversation".

### D. Evaluator Defaults Changed to vLLM Server

All evaluator LLMs now point to the local vLLM server model instead of OpenAI/Anthropic.

**`src/tau2/config.py`** — Changed:
```
DEFAULT_LLM_NL_ASSERTIONS       = "openai/Qwen/Qwen3-30B-A3B-Thinking-2507"  # was gpt-4.1
DEFAULT_LLM_ENV_INTERFACE        = "openai/Qwen/Qwen3-30B-A3B-Thinking-2507"  # was gpt-4.1
DEFAULT_LLM_EVAL_USER_SIMULATOR  = "openai/Qwen/Qwen3-30B-A3B-Thinking-2507"  # was claude-opus-4-5
```

To revert to the original evaluator models, change these back in `src/tau2/config.py` (lines 23–31).

### E. Tool Call Argument Parsing Fix

vLLM + Hermes parser sometimes returns empty `arguments` for tool calls, causing a
`JSONDecodeError: Expecting value: line 1 column 1 (char 0)` crash.

**`src/tau2/utils/llm_utils.py` — line ~446** (in `generate()`)
Changed `json.loads(tool_call.function.arguments)` to gracefully handle empty/malformed
arguments by falling back to `{}` instead of crashing the entire simulation.
