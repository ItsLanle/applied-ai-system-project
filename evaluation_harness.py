#!/usr/bin/env python3
"""
BugHound Evaluation Harness

Runs the BugHound agent on a set of predefined test cases and generates
a summary report with pass/fail rates, confidence scores, and other metrics.

Test cases are loaded from the sample_code/ directory.
"""

import os
import sys
from pathlib import Path
from typing import Dict, List, Any
from collections import defaultdict

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from bughound_agent import BugHoundAgent
from llm_client import GeminiClient, MockClient


def load_test_cases() -> List[Dict[str, Any]]:
    """Load test cases from sample_code directory."""
    sample_dir = project_root / "sample_code"
    test_cases = []

    for file_path in sample_dir.glob("*.py"):
        with open(file_path, 'r', encoding='utf-8') as f:
            code = f.read()
        test_cases.append({
            'name': file_path.stem,
            'code': code,
            'file_path': str(file_path)
        })

    return test_cases


def run_evaluation(test_cases: List[Dict[str, Any]], use_gemini: bool = False) -> Dict[str, Any]:
    """Run evaluation on all test cases."""
    results = []

    # Initialize client
    client = None
    mode = "heuristic"
    if use_gemini:
        try:
            client = GeminiClient()
            mode = "gemini"
        except RuntimeError:
            print("Gemini API key not available, falling back to heuristic mode.")
            client = None
            mode = "heuristic"

    agent = BugHoundAgent(client=client)

    for test_case in test_cases:
        print(f"Running {mode} mode on {test_case['name']}...")
        result = agent.run(test_case['code'])

        # Extract key metrics
        risk_score = result['risk'].get('score', 0)
        should_autofix = result['risk'].get('should_autofix', False)
        risk_level = result['risk'].get('level', 'unknown')
        num_issues = len(result['issues'])

        test_result = {
            'name': test_case['name'],
            'mode': mode,
            'risk_score': risk_score,
            'should_autofix': should_autofix,
            'risk_level': risk_level,
            'num_issues': num_issues,
            'issues': result['issues'],
            'fixed_code_length': len(result['fixed_code'].strip())
        }
        results.append(test_result)

    return {
        'mode': mode,
        'results': results
    }


def generate_summary(eval_results: Dict[str, Any]) -> str:
    """Generate a human-readable summary report."""
    results = eval_results['results']
    mode = eval_results['mode']

    if not results:
        return "No test cases found."

    total_tests = len(results)
    autofix_count = sum(1 for r in results if r['should_autofix'])
    avg_risk_score = sum(r['risk_score'] for r in results) / total_tests
    avg_issues = sum(r['num_issues'] for r in results) / total_tests

    # Group by risk level
    risk_levels = defaultdict(int)
    for r in results:
        risk_levels[r['risk_level']] += 1

    # Pass/fail: consider "pass" if should_autofix (low risk)
    pass_rate = (autofix_count / total_tests) * 100

    summary = f"""
BugHound Evaluation Report - {mode.title()} Mode
{'='*50}

Test Summary:
- Total test cases: {total_tests}
- Pass rate (auto-fix approved): {pass_rate:.1f}% ({autofix_count}/{total_tests})
- Average risk score: {avg_risk_score:.1f}/100
- Average issues detected: {avg_issues:.1f}

Risk Level Distribution:
"""

    for level in ['low', 'medium', 'high']:
        count = risk_levels.get(level, 0)
        pct = (count / total_tests) * 100
        summary += f"- {level.title()}: {count} ({pct:.1f}%)\n"

    summary += "\nDetailed Results:\n"
    for result in results:
        status = "PASS" if result['should_autofix'] else "FAIL"
        summary += f"- {result['name']}: {status} (risk: {result['risk_score']}, issues: {result['num_issues']})\n"

    return summary.strip()


def main():
    """Main evaluation function."""
    print("BugHound Evaluation Harness")
    print("=" * 30)

    # Load test cases
    test_cases = load_test_cases()
    print(f"Loaded {len(test_cases)} test cases from sample_code/")

    if not test_cases:
        print("No test cases found. Please add Python files to sample_code/")
        return

    # Run heuristic evaluation
    print("\nRunning heuristic mode evaluation...")
    heuristic_results = run_evaluation(test_cases, use_gemini=False)
    heuristic_summary = generate_summary(heuristic_results)
    print(heuristic_summary)

    # Try Gemini mode if API key available
    try:
        GeminiClient()
        has_gemini = True
    except RuntimeError:
        has_gemini = False

    if has_gemini:
        print("\n" + "="*50)
        print("Running Gemini mode evaluation...")
        gemini_results = run_evaluation(test_cases, use_gemini=True)
        gemini_summary = generate_summary(gemini_results)
        print(gemini_summary)
    else:
        print("\nGemini mode skipped (API key not available)")

    print("\nEvaluation complete!")


if __name__ == "__main__":
    main()