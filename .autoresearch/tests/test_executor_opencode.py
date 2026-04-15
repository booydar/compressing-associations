import sys
import os
import tempfile
sys.path.insert(0, os.path.abspath(".."))
sys.path.insert(0, os.path.abspath(".autoresearch"))
from executor import execute

# Create a dummy file to test
with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".py", dir=".") as f:
    f.write("def hello():\n    print(\"world\")\n")
    target_path = f.name

try:
    hypothesis = {
        "instruction": "Change the print statement to print \"opencode\"",
        "rationale": "Testing opencode executor",
        "target_component": target_path
    }
    provider_cfg = {
        "provider": "local",
        "model": "llama_local/unsloth/Qwen3.5-122B-A10B-GGUF",
        "host": "127.0.0.1",
        "port": 8117
    }
    
    print(f"Testing execute() on {target_path}...")
    with open(target_path, "r") as f:
        file_content = f.read()
        
    result = execute(hypothesis, file_content, provider_cfg)
    print("--- Result ---")
    print(result)
    print("--------------")
    
    if "opencode" in result:
        print("Test passed: opencode modified the file successfully!")
    else:
        print("Test failed: opencode did not modify the file as expected.")
finally:
    if os.path.exists(target_path):
        os.remove(target_path)
