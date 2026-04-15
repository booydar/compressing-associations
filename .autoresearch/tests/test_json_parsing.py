#!/usr/bin/env python3
"""
Test script for Qwen3.5 thinking model JSON parsing.
Tests extraction of JSON from various response formats:
1. Pure JSON (no thinking)
2. JSON wrapped in markdown fences
3. JSON after </thinking> tag
4. JSON embedded in reasoning text
5. Truncated/incomplete JSON
"""

import json
import re
import sys
from pathlib import Path

SAMPLE_RESPONSES = {
    "pure_json": """{
  "hypothesis": "Adjusting weight decay will find the optimal regularization regime.",
  "target_component": ".autoresearch/experiment_config.yaml",
  "rationale": "Human Direction #1 requires hyperparameter exploration.",
  "instruction": "Set weight_decay to 0.01 in experiment_config.yaml"
}""",

    "markdown_fenced": """```json
{
  "hypothesis": "Adding memory gating will improve selective retrieval.",
  "target_component": "modeling_rmt/huggingface_rmca_v3.py",
  "rationale": "Previous gating attempts failed due to timeout.",
  "instruction": "Add memory gating module before cross-attention layer"
}
```""",

    "thinking_tag": """<thinking>
I need to analyze the current state. The model is at N=16 with EM=0.0.
Previous attempts at gating caused timeouts. I should consider a simpler approach.
</thinking>
{
  "hypothesis": "Adding learnable memory temperature will improve token selection.",
  "target_component": "modeling_rmt/huggingface_rmca_v3.py",
  "rationale": "Temperature scaling is lighter than full gating mechanism.",
  "instruction": "Add temperature parameter to cross-attention softmax"
}""",

    "thinking_process": """Thinking Process:

1. **Analyze the Request:**
   - Role: Research scientist
   - Task: Propose ONE change to improve EM accuracy
   
2. **Analyze Current State:**
   - N=16, EM=0.0
   - Previous gating attempts timed out

3. **Decision:**
   I will propose a temperature scaling change.

{
  "hypothesis": "Temperature scaling improves memory token selection efficiency.",
  "target_component": "modeling_rmt/huggingface_rmca_v3.py",
  "rationale": "Lighter than gating, addresses N=16 scaling issue.",
  "instruction": "Add self.memory_temperature = nn.Parameter(torch.tensor(1.0))"
}""",

    "reasoning_then_json": """I've analyzed the experiment history. The key issue is memory retention across 16 recurrent steps. LayerNorm helped at N=8 but not N=16. I think a simple temperature parameter could help without the computational overhead of gating.

{
  "hypothesis": "Learnable temperature parameter stabilizes attention at N=16.",
  "target_component": "modeling_rmt/huggingface_rmca_v3.py",
  "rationale": "Exhausted HP exploration, need architectural solution.",
  "instruction": "Add temperature scaling to attention scores before softmax"
}""",

    "empty_response": "",

    "whitespace_only": "   \n\n   ",

    "truncated_json": """{
  "hypothesis": "This hypothesis is cut off""",

    "conflict_analysis": """Thinking Process:

1. **Analyze the Request:**
   - Role: Research scientist
   - Task: Propose ONE change

2. **Evaluate Human Directions & Priority Rules:**
   - Rule 1: "If human_directions.md contains pending suggestions..."
   - Input Data Check: The prompt shows [PENDING] for hyperparameters
   
3. **Conflict Resolution:**
   The [PENDING] tag suggests HP exploration is ongoing.
   However, user instruction asks for architecture.
   This creates a conflict.

{
  "hypothesis": "Adding memory temperature scaling will improve N=16 performance.",
  "target_component": "modeling_rmt/huggingface_rmca_v3.py",
  "rationale": "HP exploration exhausted, need architectural solution for N=16 scaling.",
  "instruction": "Add self.temperature = nn.Parameter(torch.tensor(1.0)) before attention"
}""",

    "qwen_thinking_real": """<thinking>
Okay, so I need to analyze the current state of the experiment.
N=16, EM=0.0. Looking at the history, Iter 71 was kept with batch_size and max_steps changes.
The human directions say [PENDING] for hyperparameters, but the "Current Understanding" says exhausted.
This is a conflict I need to resolve.

After thinking about this, I realize that the key issue is memory retention across 16 steps.
Previous gating attempts timed out, so I need something lighter.

</thinking>
{
  "hypothesis": "Learnable memory temperature stabilizes cross-attention at N=16.",
  "target_component": "modeling_rmt/huggingface_rmca_v3.py",
  "rationale": "Core HP exhausted (Iter 1-14), Iter 71 was stability fix. Need architecture for N=16.",
  "instruction": "Add temperature parameter to cross-attention: scores = scores / temperature"
}""",

    "reasoning_with_partial_json": """I've analyzed the experiment history. The model is at N=16 with EM=0.0.
Previous attempts at gating (Iter 70) and temperature (Iter 74) timed out.
The conflict between [PENDING] human directions and exhausted HP is tricky.

Here's my proposal:

```json
{
  "hypothesis": "Simplified memory gating without residual connection reduces compute.",
  "target_component": "modeling_rmt/huggingface_rmca_v3.py",
  "rationale": "Iter 70's gating timed out. This version removes residual for lighter compute.",
  "instruction": "Add self.memory_gate = nn.Parameter(torch.zeros(1)) and apply: memory = memory * sigmoid(gate)"
}
```""",
}


def parse_json_v1(raw: str) -> dict | None:
    """Current implementation - only strips markdown fences."""
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def parse_json_v2(raw: str) -> dict | None:
    """Enhanced implementation - extracts JSON from thinking content."""
    raw = raw.strip()
    
    # Step 1: Strip markdown fences (including multi-line)
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    raw = re.sub(r"```[\s\S]*?```", "", raw)
    
    # Step 2: Remove <thinking>...</thinking> blocks
    raw = re.sub(r"<thinking>.*?</thinking>", "", raw, flags=re.DOTALL | re.IGNORECASE)
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL | re.IGNORECASE)
    
    # Step 3: More aggressive removal of thinking headers
    # Remove everything from "Thinking Process" or "Thought:" to first {
    raw = re.sub(r"^(Thought:|Thinking Process:|Thought Process:).*?(?=\s*\{)", "", raw, flags=re.DOTALL | re.IGNORECASE)
    
    # Remove numbered analysis blocks (1. **Header**:, 2. **Header**:, etc)
    raw = re.sub(r"^\s*\d+\.\s*\*\*.*?\*\*:.*?(\n\s*\d+\.|$)", "", raw, flags=re.DOTALL)
    
    # Remove lines starting with asterisks or dashes (bullet points before JSON)
    raw = re.sub(r"^(\s*[-*]\s*.*?)+(?=\s*\{)", "", raw, flags=re.DOTALL)
    
    # Remove text that looks like analysis but not JSON
    raw = re.sub(r"^(This creates a conflict|I need to analyze|Looking at|However,|Given the|Wait,|Re-evaluating|Decision:|BUT|However,).*?(?=\s*\{|$)", "", raw, flags=re.DOTALL | re.IGNORECASE)
    
    # Step 4: Find ALL potential JSON objects and return the best one
    json_objects = []
    i = 0
    while i < len(raw):
        if raw[i] == '{':
            depth = 0
            start = i
            in_string = False
            escape = False
            for j in range(i, len(raw)):
                if escape:
                    escape = False
                    continue
                if raw[j] == '\\':
                    escape = True
                    continue
                if raw[j] == '"':
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if raw[j] == '{':
                    depth += 1
                elif raw[j] == '}':
                    depth -= 1
                    if depth == 0:
                        candidate = raw[start:j+1]
                        try:
                            parsed = json.loads(candidate)
                            # Check if it has expected keys
                            has_hypothesis = "hypothesis" in parsed
                            has_target = "target_component" in parsed
                            has_instruction = "instruction" in parsed
                            json_objects.append((len(candidate), parsed, has_hypothesis and has_target and has_instruction))
                        except json.JSONDecodeError:
                            pass
                        i = j
                        break
        i += 1
    
    # Return the JSON with all required keys, or the largest one
    if json_objects:
        # Prefer objects with all required keys
        complete = [obj for obj in json_objects if obj[2]]
        if complete:
            return complete[0][1]
        json_objects.sort(key=lambda x: x[0], reverse=True)
        return json_objects[0][1]
    
    return None


def parse_json_v3(raw: str) -> dict | None:
    """Most aggressive - find ANY valid JSON object in the response."""
    raw = raw.strip()
    
    # Strip markdown fences
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    raw = re.sub(r"```[\s\S]*?```", "", raw)
    
    # Remove common thinking markers (more aggressive)
    raw = re.sub(r"<thinking>.*?</thinking>", "", raw, flags=re.DOTALL | re.IGNORECASE)
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL | re.IGNORECASE)
    raw = re.sub(r"^(Thought:|Thinking Process:|Thought Process:|## Thinking).*?(?=\s*\{)", "", raw, flags=re.DOTALL | re.IGNORECASE)
    
    # Remove analysis paragraphs before JSON
    raw = re.sub(r"^\s*(I [a-z]+|Looking at|However|Therefore|Given|Since|Because|The fact that|This means|So |Wait|But ).*?(?=\s*\{)", "", raw, flags=re.DOTALL | re.IGNORECASE)
    
    # Find all potential JSON objects (balanced braces)
    json_objects = []
    i = 0
    while i < len(raw):
        if raw[i] == '{':
            depth = 0
            start = i
            in_string = False
            escape = False
            for j in range(i, len(raw)):
                if escape:
                    escape = False
                    continue
                if raw[j] == '\\':
                    escape = True
                    continue
                if raw[j] == '"':
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if raw[j] == '{':
                    depth += 1
                elif raw[j] == '}':
                    depth -= 1
                    if depth == 0:
                        candidate = raw[start:j+1]
                        try:
                            parsed = json.loads(candidate)
                            has_hypothesis = "hypothesis" in parsed
                            has_target = "target_component" in parsed
                            has_instruction = "instruction" in parsed
                            json_objects.append((len(candidate), parsed, has_hypothesis and has_target and has_instruction))
                        except json.JSONDecodeError:
                            pass
                        i = j
                        break
        i += 1
    
    # Return the JSON with all required keys, or the largest one
    if json_objects:
        complete = [obj for obj in json_objects if obj[2]]
        if complete:
            return complete[0][1]
        json_objects.sort(key=lambda x: x[0], reverse=True)
        return json_objects[0][1]
    
    return None


def test_parsing():
    """Run tests on all sample responses."""
    print("=" * 70)
    print("Qwen3.5 Thinking Model JSON Parser Test")
    print("=" * 70)
    
    results = {}
    
    for name, response in SAMPLE_RESPONSES.items():
        print(f"\n{'─' * 70}")
        print(f"Test: {name}")
        print(f"{'─' * 70}")
        
        # V1 (current)
        v1_result = parse_json_v1(response)
        print(f"\nV1 (current): {'✓' if v1_result else '✗'}")
        if v1_result:
            print(f"  Keys: {list(v1_result.keys())}")
        
        # V2 (enhanced)
        v2_result = parse_json_v2(response)
        print(f"V2 (enhanced): {'✓' if v2_result else '✗'}")
        if v2_result:
            print(f"  Keys: {list(v2_result.keys())}")
        
        # V3 (aggressive)
        v3_result = parse_json_v3(response)
        print(f"V3 (aggressive): {'✓' if v3_result else '✗'}")
        if v3_result:
            print(f"  Keys: {list(v3_result.keys())}")
        
        # Compare
        results[name] = {
            "v1": v1_result is not None,
            "v2": v2_result is not None,
            "v3": v3_result is not None,
        }
    
    # Summary
    print(f"\n{'═' * 70}")
    print("Summary")
    print(f"{'═' * 70}")
    
    for name in SAMPLE_RESPONSES:
        v1, v2, v3 = results[name]["v1"], results[name]["v2"], results[name]["v3"]
        print(f"{name:25} | V1: {'✓' if v1 else '✗'} | V2: {'✓' if v2 else '✗'} | V3: {'✓' if v3 else '✗'}")
    
    # Find best version
    v1_success = sum(1 for r in results.values() if r["v1"])
    v2_success = sum(1 for r in results.values() if r["v2"])
    v3_success = sum(1 for r in results.values() if r["v3"])
    
    print(f"\nTotal success: V1={v1_success}/{len(SAMPLE_RESPONSES)}, V2={v2_success}/{len(SAMPLE_RESPONSES)}, V3={v3_success}/{len(SAMPLE_RESPONSES)}")
    
    return results


if __name__ == "__main__":
    results = test_parsing()
    
    # Exit with error if any test failed completely
    all_failed = all(not any(r.values()) for r in results.values())
    sys.exit(1 if all_failed else 0)
