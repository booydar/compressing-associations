import subprocess
import os
import tempfile

def test_opencode_call():
    # Create a temporary file to modify in the current directory
    with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.txt', dir='.') as temp_file:
        temp_file.write("Hello world\n")
        temp_file_path = temp_file.name
        
    # Get absolute path for the prompt
    abs_temp_file_path = os.path.abspath(temp_file_path)

    print(f"Created temporary file at {abs_temp_file_path}")

    try:
        # The prompt for opencode
        prompt = f"Please modify the file {abs_temp_file_path} by replacing 'Hello world' with 'Hello opencode'."
        
        # Call opencode
        print(f"Calling opencode with prompt: {prompt}")
        
        # Set environment variables for OpenAI compatible endpoint
        env = os.environ.copy()
        env["OPENAI_BASE_URL"] = "http://127.0.0.1:8117/v1"
        env["OPENAI_API_KEY"] = "no-key"
        
        # Use the openai provider prefix for the local model
        model_name = "llama_local/unsloth/Qwen3.5-122B-A10B-GGUF"
        
        result = subprocess.run(
            ["opencode", "run", "-m", model_name, prompt],
            capture_output=True,
            text=True,
            env=env
        )
        
        print(f"opencode return code: {result.returncode}")
        print(f"opencode stdout:\n{result.stdout}")
        print(f"opencode stderr:\n{result.stderr}")
        
        # Verify the file was modified
        with open(temp_file_path, 'r') as f:
            content = f.read()
            
        print(f"File content after opencode:\n{content}")
        
        assert "Hello opencode" in content, "opencode failed to modify the file correctly"
        print("Test passed successfully!")
        
    finally:
        # Clean up
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)

if __name__ == "__main__":
    test_opencode_call()
