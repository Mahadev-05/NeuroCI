import asyncio
from src.models import AgentState, FailureCategory, ParsedError
from src.agent.classifier import classify_failure
from src.agent.patch_generator import generate_patch

async def main():
    print("Starting NeuroCI Interactive Demo...")
    print("Select a CI failure scenario to test:")
    print("1. Test Assertion Error (Division by Zero)")
    print("2. Dependency Version Conflict (boto3 / botocore)")
    print("3. Missing Environment Variable (DATABASE_URL)")
    
    choice = input("\nEnter choice (1-3): ").strip()
    
    if choice == "2":
        log_file = "003_dep_conflict_boto3.txt"
        file_path = "requirements.txt"
        language = "requirements"
        error_type = "DependencyConflict"
        error_msg = "boto3 1.28.0 requires botocore<1.31.1,>=1.31.0"
        line_num = 2
        file_content = "Flask==2.0.1\nbotocore==1.29.76\nboto3==1.28.0\n"
        print("\nLoading sample CI failure log: '003_dep_conflict_boto3.txt'\n")
    elif choice == "3":
        log_file = "007_config_missing_env.txt"
        file_path = "src/config.py"
        language = "python"
        error_type = "KeyError"
        error_msg = "'DATABASE_URL'"
        line_num = 4
        file_content = "import os\n\n# Database configuration\nDATABASE_URL = os.environ[\"DATABASE_URL\"]\nDEBUG = True\n"
        print("\nLoading sample CI failure log: '007_config_missing_env.txt'\n")
    else:
        log_file = "005_test_assertion_divide.txt"
        file_path = "tests/test_calculator.py"
        language = "python"
        error_type = "AssertionError"
        error_msg = "assert inf == 0"
        line_num = 25
        file_content = "import pytest\n\nclass Calculator:\n    def divide(self, a, b):\n        if b == 0:\n            return float('inf')\n        return a / b\n\ncalculator = Calculator()\n\ndef test_divide_by_zero():\n    result = calculator.divide(10, 0)\n    assert result == 0\n"
        print("\nLoading sample CI failure log: '005_test_assertion_divide.txt'\n")

    with open(f"tests/fixtures/sample_logs/{log_file}", "r") as f:
        log_content = f.read()

    state = AgentState(
        run_id=999,
        repo_full_name="demo/app",
        head_branch="main",
        head_sha="abcdef123456",
        workflow_name="CI",
        run_url="http://localhost",
        parsed_error=ParsedError(
            raw_log=log_content,
            error_type=error_type,
            error_message=error_msg,
            file_path=file_path,
            line_number=line_num,
            language=language
        ),
        file_content=file_content
    )
    
    print("[1] Classifying the failure...")
    state = await classify_failure(state)
    print(f"   => Detected Category: {state.category.value}")
    if state.category == FailureCategory.UNKNOWN:
        print(f"   => Unable to classify with high confidence. Proceeding anyway for demo.")
    
    print("\n[2] Generating code patch via LLM (Chain of Thought)...")
    state = await generate_patch(state)
    
    if state.patch:
        print("\nPatch successfully generated!")
        print(f"   => Confidence: {state.patch.confidence * 100:.1f}%")
        print("\n--- Proposed Unified Diff ---")
        print(state.patch.unified_diff)
        print("-----------------------------\n")
        print("Reasoning:")
        print(state.patch.reasoning)
    else:
        print("\nFailed to generate patch.")

if __name__ == "__main__":
    asyncio.run(main())
