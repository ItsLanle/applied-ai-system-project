import os
import re
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Optional


class TestDebugAgent:
    """
    Test-Failure Debugging Tutor workflow:

    1) PLAN:     Set up context
    2) RUN:      Execute the test to capture actual error output
    3) ANALYZE:  Translate the error into plain English
    4) IDENTIFY: Find the root cause (where + why)
    5) TEACH:    Explain the concept, common mistake, best practice + tip
    """

    def __init__(self, client: Optional[Any] = None):
        self.client = client
        self.logs: List[Dict[str, str]] = []

    # ----------------------------
    # Public API
    # ----------------------------
    def run(self, code: str, test_code: str, expected_output: str = "") -> Dict[str, Any]:
        self.logs = []
        self._log("PLAN", "Setting up test-failure debugging tutor workflow.")

        if test_code.strip():
            test_output = self._run_test(code, test_code)
            failed = any(
                kw in test_output
                for kw in ("Error", "FAILED", "assert", "Traceback")
            )
            self._log("RUN", f"Test executed. {'Failure detected.' if failed else 'No obvious failure captured.'}")
        else:
            test_output = ""
            self._log("RUN", "No test provided — skipping execution. Analyzing code directly.")

        if self._can_call_llm():
            analysis = self._llm_debug(code, test_code, expected_output, test_output)
        else:
            analysis = self._heuristic_debug(code, test_code, test_output)

        self._log("ANALYZE", "Error translated into plain English.")
        self._log("IDENTIFY", "Root cause located.")
        self._log("TEACH", "Concept, common mistake, best practice, and tip prepared.")

        return {
            "plain_english": analysis.get("plain_english", ""),
            "root_cause": analysis.get("root_cause", ""),
            "fixed_code": analysis.get("fixed_code", ""),
            "concept": analysis.get("concept", ""),
            "common_mistake": analysis.get("common_mistake", ""),
            "best_practice": analysis.get("best_practice", ""),
            "debugging_tip": analysis.get("debugging_tip", ""),
            "test_output": test_output,
            "logs": self.logs,
        }

    # ----------------------------
    # Step 2: Run the test
    # ----------------------------
    def _run_test(self, code: str, test_code: str) -> str:
        combined = code.strip() + "\n\n" + test_code.strip() + "\n"
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False
            ) as f:
                f.write(combined)
                tmp_path = f.name

            result = subprocess.run(
                [sys.executable, tmp_path],
                capture_output=True,
                text=True,
                timeout=10,
            )
            output = (result.stdout + result.stderr).strip()
            return output if output else "No output captured. The test may have passed silently."
        except subprocess.TimeoutExpired:
            return "TimeoutError: code execution exceeded 10 seconds."
        except Exception as e:
            return f"Error running test: {str(e)}"
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    # ----------------------------
    # Step 3-5: LLM tutor path
    # ----------------------------
    def _llm_debug(
        self, code: str, test_code: str, expected_output: str, test_output: str
    ) -> Dict[str, str]:
        system_prompt = (
            "You are BugHound, a patient debugging tutor for beginners. "
            "Your job is NOT just to fix code — your job is to TEACH. "
            "Explain errors in simple, friendly language a beginner can understand. "
            "Follow the output format exactly."
        )
        expected_section = (
            f"EXPECTED OUTPUT:\n{expected_output}\n\n" if expected_output.strip() else ""
        )
        task_description = (
            "A Python test is failing. Act as a debugging tutor."
            if test_code.strip()
            else "A student pasted Python code for review. Act as a debugging tutor and analyze it for bugs."
        )
        test_section = f"TEST:\n{test_code}\n\n" if test_code.strip() else ""
        actual_output_section = f"ACTUAL TEST OUTPUT:\n{test_output}\n\n" if test_output.strip() else ""
        user_prompt = (
            f"{task_description}\n\n"
            "Reply using EXACTLY this format — copy each label as-is, one per section:\n\n"
            "PLAIN_ENGLISH:\n"
            "<explain the error or issue in simple beginner-friendly language, no jargon>\n\n"
            "ROOT_CAUSE:\n"
            "<where exactly the bug is and WHY it causes the failure, reference the specific line>\n\n"
            "FIXED_CODE:\n"
            "<the corrected Python function(s) only — no test code. "
            "Add a short inline comment on EVERY line explaining what it does for a beginner>\n\n"
            "CONCEPT:\n"
            "<the programming concept this bug illustrates, in 1-2 simple sentences>\n\n"
            "COMMON_MISTAKE:\n"
            "<the common mistake pattern this represents>\n\n"
            "BEST_PRACTICE:\n"
            "<the best practice that prevents this class of bug>\n\n"
            "DEBUGGING_TIP:\n"
            "<one short reusable debugging tip relevant to this error>\n\n"
            "---\n\n"
            f"CODE:\n{code}\n\n"
            f"{test_section}"
            f"{actual_output_section}"
            f"{expected_section}"
        )

        try:
            raw = self.client.complete(system_prompt=system_prompt, user_prompt=user_prompt)
        except Exception as e:
            self._log("ANALYZE", f"API Error: {str(e)}. Falling back to heuristic tutor.")
            return self._heuristic_debug(code, test_code, test_output)

        parsed = self._parse_delimited_response(raw)
        if not parsed.get("fixed_code"):
            self._log("ANALYZE", "Could not extract fixed code from LLM response. Falling back to heuristic tutor.")
            # Preserve any fields that did parse, fill gaps with heuristics
            heuristic = self._heuristic_debug(code, test_code, test_output)
            heuristic.update({k: v for k, v in parsed.items() if v})
            return heuristic

        return parsed

    # ----------------------------
    # Step 3-5: Heuristic tutor path
    # ----------------------------
    def _annotate_lines(self, code: str, comments: dict) -> str:
        """
        Given a dict of {substring_to_match: comment}, append inline comments
        to matching lines. Lines with no match get a generic explanation.
        """
        lines = code.splitlines()
        result = []
        for line in lines:
            stripped = line.rstrip()
            if not stripped or stripped.lstrip().startswith("#"):
                result.append(stripped)
                continue
            matched_comment = None
            for keyword, comment in comments.items():
                if keyword in stripped:
                    matched_comment = comment
                    break
            if matched_comment:
                result.append(f"{stripped}  # {matched_comment}")
            else:
                # Generic line-level annotation
                if stripped.lstrip().startswith("def "):
                    result.append(f"{stripped}  # define the function and its parameters")
                elif stripped.lstrip().startswith("return "):
                    result.append(f"{stripped}  # compute and return the result")
                elif stripped.lstrip().startswith("for "):
                    result.append(f"{stripped}  # loop over each item")
                elif stripped.lstrip().startswith("if "):
                    result.append(f"{stripped}  # check this condition")
                else:
                    result.append(stripped)
        return "\n".join(result)

    def _heuristic_fix(self, code: str, test_output: str) -> str:
        """
        Try common mechanical fixes then annotate every line with a beginner comment.
        """
        import re as _re

        fixed = code

        if "IndexError" in test_output:
            fixed = _re.sub(r"range\(len\((\w+)\)\)", r"range(len(\1) - 1)", fixed)
            if fixed == code:
                fixed = code + "\n# BugHound: check your index — you may be going one step too far."
            return self._annotate_lines(fixed, {
                "range(len(": "loop up to but not including the last index to avoid going out of bounds",
                "return": "send back the result",
            })

        if "NameError" in test_output:
            match = _re.search(r"name '(\w+)' is not defined", test_output)
            if match:
                bad_name = match.group(1)
                fixed = code + f"\n# BugHound: '{bad_name}' is not defined — check spelling or define it first."
            else:
                fixed = code + "\n# BugHound: a name is undefined — check spelling of all variable/function names."
            return self._annotate_lines(fixed, {})

        if "AssertionError" in test_output:
            candidates = [
                (_re.compile(r"\breturn\b(.*)(\ba\s*-\s*b\b)(.*)"),
                 r"return\1a + b\3",
                 {"a + b": "add a and b together — this was the bug, it was subtracting instead of adding"}),
                (_re.compile(r"\breturn\b(.*)(\ba\s*\*\s*b\b)(.*)"),
                 r"return\1a + b\3",
                 {"a + b": "add a and b together — this was the bug, it was multiplying instead of adding"}),
                (_re.compile(r"\[:(\w+)\s*-\s*1\]"),
                 r"[:\1]",
                 {"[:": "slice the list up to index n — removed the -1 that was cutting one item too short"}),
                (_re.compile(r"n\s*%\s*2\s*==\s*1"),
                 "n % 2 == 0",
                 {"% 2 == 0": "remainder is 0 when n is even — this was the bug, it was checking for odd instead"}),
            ]
            extra_comments = {}
            for pattern, replacement, comments in candidates:
                attempt = pattern.sub(replacement, fixed)
                if attempt != fixed:
                    fixed = attempt
                    extra_comments = comments
                    break
            else:
                lines = code.splitlines()
                annotated = []
                for line in lines:
                    annotated.append(line)
                    if "return" in line:
                        annotated.append(
                            "# BugHound: check the operator/logic on the line above — "
                            "is it doing what you intended?"
                        )
                fixed = "\n".join(annotated)
            return self._annotate_lines(fixed, extra_comments)

        # Generic fallback
        return self._annotate_lines(
            code + "\n# BugHound: switch to Gemini mode for an AI-powered fix.",
            {},
        )

    def _heuristic_debug(
        self, code: str, test_code: str, test_output: str
    ) -> Dict[str, str]:
        plain_english = test_output or "The test failed."
        root_cause = "Enable Gemini mode for an AI-powered root cause analysis."
        fixed_code = self._heuristic_fix(code, test_output)
        concept = ""
        common_mistake = ""
        best_practice = ""
        debugging_tip = "Add a print() inside your function to see what it actually returns."

        if "AssertionError" in test_output:
            plain_english = (
                "Your function returned a value that didn't match what the test expected. "
                "Python checked the result and said 'that's not right!' — but it didn't tell you why. "
                "That's your job to figure out by looking at the logic inside the function."
            )
            root_cause = (
                "The assertion failed because the function's output didn't equal the expected value. "
                "Look carefully at every operator (+, -, *, /) and every condition (>, <, ==) in the function — "
                "one of them is probably doing the opposite of what you intended."
            )
            concept = (
                "An AssertionError means 'I expected X but got Y.' "
                "Tests use assert statements to verify that code behaves correctly. "
                "When they fail, it means the logic in your function is off, not necessarily the syntax."
            )
            common_mistake = (
                "Using the wrong operator (like `-` instead of `+`) is one of the most common beginner bugs. "
                "The code looks almost right, which makes it hard to spot."
            )
            best_practice = (
                "Before writing the function, write down in plain English what it should do step by step. "
                "Then translate each step into code — this keeps your operators matching your intent."
            )
            debugging_tip = (
                "Add `print(result)` just before your return statement to see what the function "
                "is actually returning, then compare it to what the test expects."
            )

        elif "NameError" in test_output:
            plain_english = (
                "Python couldn't find something it was looking for — a variable or function name "
                "that you used doesn't exist. It's like calling someone by the wrong name."
            )
            root_cause = (
                "A NameError means you used a name (variable or function) that Python has never seen before. "
                "This is usually a typo or a case-sensitivity issue (Python treats `myVar` and `myvar` as different)."
            )
            concept = (
                "In Python, you must define a variable before you use it. "
                "If the name doesn't match exactly — including uppercase and lowercase letters — Python can't find it."
            )
            common_mistake = "Typos in variable or function names, or mixing up capitalization."
            best_practice = "Use short, consistent names and double-check spelling when you get a NameError."
            debugging_tip = "Copy the exact name from the error message and search for it in your code."

        elif "TypeError" in test_output:
            plain_english = (
                "Python tried to do an operation on the wrong type of value. "
                "It's like trying to add a word and a number together — Python doesn't know how."
            )
            root_cause = (
                "A TypeError means the data type of a value doesn't match what the operation requires. "
                "For example, adding a string to an integer, or calling a function with the wrong number of arguments."
            )
            concept = (
                "Python is strict about types. You can't add a string and an integer without converting one of them first. "
                "Functions also expect a specific number of arguments — too few or too many causes a TypeError."
            )
            common_mistake = "Forgetting to convert types (e.g. int() or str()) before using them together."
            best_practice = "Check what types your function expects and what types it receives by printing them."
            debugging_tip = "Use `print(type(variable))` to check the type of any value you're unsure about."

        elif "SyntaxError" in test_output:
            plain_english = (
                "Python couldn't even read your code — there's a grammar mistake. "
                "It's like writing a sentence without proper punctuation; Python gets confused and stops."
            )
            root_cause = (
                "A SyntaxError means Python found code it couldn't parse. "
                "Common causes: missing colon after `if`/`for`/`def`, unmatched parentheses, or an extra/missing quote."
            )
            concept = (
                "Python has strict grammar rules (called syntax). "
                "If any rule is broken, Python refuses to run the entire file — even the parts that are correct."
            )
            common_mistake = "Missing a `:` at the end of `def`, `if`, `for`, or `while` lines."
            best_practice = "Read the SyntaxError message — it usually tells you the exact line where Python got confused."
            debugging_tip = "Check the line number in the error and also the line just above it — the real mistake is often one line earlier."

        elif "IndexError" in test_output:
            plain_english = (
                "You tried to access an item in a list using a position number that doesn't exist. "
                "Imagine a list of 3 items — asking for item #5 will cause this error."
            )
            root_cause = (
                "An IndexError means you went out of bounds. "
                "Python lists start at index 0, so a list with 3 items has valid indexes 0, 1, and 2. "
                "Anything higher causes this error."
            )
            concept = (
                "List indexes in Python start at 0, not 1. "
                "A list with n items has valid indexes from 0 to n-1."
            )
            common_mistake = (
                "Off-by-one errors — loops or index calculations that go one step too far. "
                "This is one of the most classic bugs in all of programming."
            )
            best_practice = "Use `range(len(my_list))` to iterate safely, or better yet, iterate directly: `for item in my_list:`."
            debugging_tip = "Print `len(your_list)` and your index value side by side to see if the index exceeds the length."

        return {
            "plain_english": plain_english,
            "root_cause": root_cause,
            "fixed_code": fixed_code,
            "concept": concept,
            "common_mistake": common_mistake,
            "best_practice": best_practice,
            "debugging_tip": debugging_tip,
        }

    # ----------------------------
    # Parsing utilities
    # ----------------------------
    def _parse_delimited_response(self, text: str) -> Dict[str, str]:
        """
        Parse the custom-delimited LLM response format.
        Each section starts with a LABEL: line and runs until the next label or end.
        This avoids all JSON multiline issues.
        """
        labels = {
            "PLAIN_ENGLISH": "plain_english",
            "ROOT_CAUSE": "root_cause",
            "FIXED_CODE": "fixed_code",
            "CONCEPT": "concept",
            "COMMON_MISTAKE": "common_mistake",
            "BEST_PRACTICE": "best_practice",
            "DEBUGGING_TIP": "debugging_tip",
        }
        result: Dict[str, str] = {v: "" for v in labels.values()}

        current_key = None
        buffer: List[str] = []

        def flush():
            if current_key:
                result[current_key] = "\n".join(buffer).strip()

        for line in text.splitlines():
            matched = False
            # Strip markdown bold/italic markers so **LABEL:** and LABEL: both match
            clean_line = re.sub(r"[\*_]+", "", line.strip()).strip()
            for label, key in labels.items():
                if clean_line.upper().startswith(label + ":"):
                    flush()
                    buffer = []
                    current_key = key
                    # Content may appear on the same line after the colon
                    after = clean_line[len(label) + 1:].strip()
                    if after:
                        buffer.append(after)
                    matched = True
                    break
            if not matched and current_key:
                buffer.append(line)

        flush()

        if result.get("fixed_code"):
            result["fixed_code"] = self._strip_code_fences(result["fixed_code"])

        return result

    def _strip_code_fences(self, text: str) -> str:
        text = text.strip()
        match = re.search(
            r"```\w*\s*(.*?)\s*```", text, flags=re.DOTALL
        )
        if match:
            return match.group(1)
        return text

    def _can_call_llm(self) -> bool:
        return self.client is not None and hasattr(self.client, "complete")

    def _log(self, step: str, message: str) -> None:
        self.logs.append({"step": step, "message": message})
