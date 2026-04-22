# BugHound Mini Model Card (Reflection)

Fill this out after you run BugHound in **both** modes (Heuristic and Gemini).

---

## 1) What is this system?

**Name:** BugHound  
**Purpose:** Analyze a Python snippet, propose a fix, and run reliability checks before suggesting whether the fix should be auto-applied.

**Intended users:** Students learning agentic workflows and AI reliability concepts.

---

## 2) How does it work?

BugHound follows a five-step agentic loop: **PLAN → ANALYZE → ACT → TEST → REFLECT**.

- **PLAN**: The agent initializes state and logs the start of analysis.
- **ANALYZE**: In Heuristic mode, pattern-matching rules scan the code for known anti-patterns (bare `except:`, `print()` statements, `TODO` comments). In Gemini mode, the snippet is sent to `gemini-2.5-flash` with a structured prompt requesting a JSON list of `{type, severity, msg}` issues.
- **ACT**: Heuristics apply deterministic textual substitutions (e.g., `except:` → `except Exception as e:`). Gemini mode sends the issues and original code back to the model and asks for a corrected version of the full snippet.
- **TEST**: The `assess_risk()` function scores the proposed fix on a 0–100 scale. It penalizes high-severity issues (−40), medium (−20), low (−5), structural shrinkage (fewer lines, missing returns), and any modification to bare exception handlers.
- **REFLECT**: If the risk score is ≥ 75 ("low risk"), the fix is auto-applied. Otherwise, the fix is shown to the user for manual review.

If the Gemini API fails at any step (rate limit, network error, unparseable JSON), the agent automatically falls back to heuristic mode and logs a warning.

---

## 3) Inputs and outputs

**Inputs:**

- Short Python functions and scripts — typically 5–30 lines.
- Common "shapes" tested: bare `except:` blocks, functions using `print()` instead of logging, code with `TODO` comments, and simple logic bugs (e.g., off-by-one in a loop).
- Also tested: a multi-line try/except with no return in the `except` branch, and a snippet mixing `print()` + bare `except:` in the same function.

**Outputs:**

- **Issues detected**: bare exception handling (`except:`), debug print statements, unresolved TODO comments, and (in Gemini mode) semantic issues like missing return values or incorrect variable names.
- **Fixes proposed**: replacing `except:` with `except Exception as e:`, swapping `print()` for `logging.info()` with an added `import logging`, and (in Gemini mode) full rewrites that address logic errors.
- **Risk report**: a score (0–100), a level (`low` / `medium` / `high`), a list of reasons (e.g., "bare except modified", "line count reduced"), and a boolean `should_autofix`.

---

## 4) Reliability and safety rules

**Rule 1 — High-severity issue detected (−40 points)**

- *What it checks*: Whether any detected issue is labeled `"high"` severity.
- *Why it matters*: High-severity issues (e.g., swallowing exceptions silently, logic that could corrupt data) represent the highest risk of introducing a regression. Aggressively penalizing them keeps the auto-fix threshold conservative.
- *False positive*: A cosmetic rename flagged as high-severity by Gemini would unfairly tank the score on a safe fix.
- *False negative*: If Gemini classifies a dangerous issue as `"medium"`, this rule never fires and the fix could still score high enough to auto-apply.

**Rule 2 — Removed return statement (−30 points)**

- *What it checks*: Whether the original code contains a `return` keyword but the proposed fix does not.
- *Why it matters*: Removing a `return` changes the function's contract — callers expecting a value would receive `None`, silently breaking dependent code.
- *False positive*: A fix that correctly removes a `return` from a function that was *mistakenly* returning a value (e.g., a `void`-style helper) would be penalized even though the removal is correct.
- *False negative*: The rule checks for the literal string `return` via `in`. If the fix adds a return inside a nested lambda or list comprehension rather than the top-level function, the rule may miss a genuine removal.

---

## 5) Observed failure modes

**Failure 1 — Missed semantic bug (heuristic mode)**

Snippet:
```python
def average(nums):
    total = 0
    for n in nums:
        total += n
    return total / len(nums)
```
BugHound (heuristic mode) reported **no issues**. The function raises `ZeroDivisionError` when `nums` is empty, but none of the three heuristic patterns (`print`, `except:`, `TODO`) match. The agent confidently returned a clean bill of health for code that crashes on a common edge case. Heuristics are purely syntactic and cannot reason about runtime behavior.

**Failure 2 — Unnecessary / overly broad fix (Gemini mode)**

Snippet:
```python
def read_file(path):
    try:
        with open(path) as f:
            return f.read()
    except Exception as e:
        print(f"Error: {e}")
```
Gemini rewrote the entire function, renamed the variable `path` to `file_path`, added `import logging`, replaced `print` with `logging.error`, and added a `return None` in the except branch. While not wrong, the rename was an unrequested behavior change, and `return None` made the fix *look* riskier to the risk assessor (line count increased, bare except was touched), causing it to score as `medium` rather than `low` — meaning the user had to manually approve a fix that was arguably correct.

---

## 6) Heuristic vs Gemini comparison

- **What Gemini detected that heuristics did not**: Logic bugs (missing guard clauses, incorrect operator usage, missing `return` in a branch), poorly named variables, and missing docstrings. Gemini also assigned more precise severity levels, distinguishing between a cosmetic issue and a functional one.
- **What heuristics caught consistently**: `print()` statements, bare `except:` blocks, and `TODO` comments — every time, with zero latency and no API cost.
- **How fixes differed**: Heuristic fixes are surgical and predictable — a one-line substitution at most. Gemini fixes are holistic rewrites that sometimes fix multiple issues at once but can also introduce unrequested changes.
- **Risk scorer agreement**: The risk scorer agreed with intuition for heuristic fixes (small, targeted changes scored low risk). For Gemini fixes it was less consistent — rewrites that restructured code sometimes scored `medium` even when the logic was clearly correct, because the line-count and return-statement rules are structural, not semantic.

---

## 7) Evaluation Harness (Stretch Feature)

To demonstrate measurable performance and reliability, I implemented an evaluation harness (`evaluation_harness.py`) that runs the agent on predefined test cases and generates summary metrics.

**Test Setup:**
- **Test Cases**: 4 Python snippets from `sample_code/` (cleanish.py, flaky_try_except.py, print_spam.py, mixed_issues.py)
- **Modes Tested**: Heuristic mode (always available), Gemini mode (when API key is configured)
- **Metrics Collected**: Pass/fail rate (based on auto-fix approval), risk scores, issue counts, risk level distribution

**Results (Heuristic Mode):**
- **Pass Rate**: 50.0% (2/4 fixes auto-approved)
- **Average Risk Score**: 70.0/100
- **Average Issues Detected**: 1.2 per test case
- **Risk Distribution**: 50% low, 25% medium, 25% high

**Key Insights:**
- The harness provides objective measurement of system performance
- Pass/fail is determined by the risk assessor's `should_autofix` flag (score ≥75)
- Confidence ratings are represented by risk scores (higher = more confident in safety)
- This evaluation demonstrates the system's reliability guardrails in action

## 7) Human-in-the-loop decision

**Scenario**: The proposed fix removes or restructures exception handling in code that interacts with external resources (files, databases, network calls).

- **Trigger**: Add a rule in `assess_risk` that checks whether the original code contained `open(`, `requests.`, `cursor.execute(`, or similar I/O calls *and* the fix alters the `except` block. Any such combination should force `should_autofix = False` regardless of score.
- **Where to implement**: Primarily in `risk_assessor.py` inside `assess_risk()`, since that function is the single gate controlling the auto-fix decision. A secondary label ("I/O exception handling changed") should also surface in the `reasons` list so the agent's REFLECT step can echo it to the user.
- **Message to show**: *"BugHound changed exception handling in code that touches external resources. Auto-fix is disabled. Please review the proposed change and confirm it handles all failure modes (file not found, network timeout, permission denied) before applying."*

---

## 8) Improvement idea

**Minimal-diff enforcement via AST comparison**

Currently, Gemini is asked to return a corrected version of the full snippet, but there is no check that the rewrite is actually minimal. This causes false positives in the risk scorer (line count changes, unrequested renames) and erodes trust.

**Improvement**: After receiving Gemini's fixed code, parse both the original and the fix with Python's `ast` module and compare only the *changed nodes*. If more than one top-level statement changed and only one issue was reported, penalize the score with a new reason: `"fix modifies more than the identified issue"`. This single guardrail would catch over-broad rewrites without adding a second LLM call, and would make the risk scorer's output far more aligned with what actually changed.
