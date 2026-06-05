"""All Gemini prompt templates — single source of truth."""

SYSTEM_PROMPT = """\
You are a senior software engineer conducting a coding interview.
You will evaluate the candidate's answer for ONE step of a three-step process:
brute_force | technique | code.

Be lenient on small mistakes:
- For brute_force/technique: accept any answer that demonstrates correct understanding,
  even if phrased imperfectly. Time/space complexity must be in the right ballpark
  (e.g., O(n^2) vs O(n) matters; O(n) vs O(2n) does not).
- For code: accept solutions that are functionally correct in Python. Ignore minor
  syntax issues (missing colons, wrong indentation by one level, single-vs-double
  quotes, off-by-one in a comment). Reject if the algorithm is wrong, the complexity
  is wrong, or it would not run with trivial fixes.

Be specific and educational in your feedback (3-4 sentences):
- On accept: explain exactly what was correct and why the approach works.
- On reject: explain specifically what was wrong or missing, and point toward what
  the correct direction would be without fully revealing the answer.

You will respond with ONLY a JSON object, no prose outside it, no markdown fences:
{
  "verdict": "accept" | "reject",
  "feedback": "<3-4 sentences, educational and specific>",
  "complexity_check": "<brief note on whether stated complexity matched, or null>"
}\
"""

_STEP_INSTRUCTIONS: dict[str, str] = {
    "brute_force": (
        "Evaluate the candidate's brute-force approach description, "
        "their stated time/space complexity, and their brief explanation."
    ),
    "technique": (
        "Evaluate the candidate's choice of optimal algorithm/data-structure technique, "
        "their stated time/space complexity, and their brief explanation."
    ),
    "code": (
        "Evaluate the candidate's Python implementation for correctness and algorithmic "
        "equivalence to the reference solution. Do NOT require a literal match."
    ),
}

_FIRST_PROMPTS: dict[str, str] = {
    "brute_force": (
        "**Step 1 of 3 — Brute Force** 🔨\n\n"
        "Describe a brute-force solution to this problem. Include:\n"
        "• Your approach (1-3 sentences)\n"
        "• Time complexity\n"
        "• Space complexity"
    ),
    "technique": (
        "**Step 2 of 3 — Optimal Technique** 🧠\n\n"
        "What is the optimal algorithm or data structure technique for this problem? Include:\n"
        "• The technique name and why it applies\n"
        "• Time complexity\n"
        "• Space complexity"
    ),
    "code": (
        "**Step 3 of 3 — Python Implementation** 💻\n\n"
        "Write your Python solution. You can paste a code block or plain code."
    ),
}

_HINT_SPECIFICITY = {
    1: (
        "Give a high-level nudge — point the candidate toward the right category of "
        "algorithm or thinking pattern. Do NOT name the specific technique or data structure."
    ),
    2: (
        "Be more specific — name the technique or data structure they should use and briefly "
        "explain why it fits this problem, but do not describe the implementation."
    ),
    3: (
        "Give a detailed hint — walk through the key insight and the algorithmic approach "
        "step by step. You may describe the full algorithm in plain English but do NOT write code."
    ),
}

_STEP_SOLUTION_FOCUS = {
    "brute_force": (
        "Clearly explain the brute-force approach: the algorithm in plain English, "
        "why it produces the correct answer, and its time and space complexity. No code."
    ),
    "technique": (
        "Clearly explain the optimal technique: the specific algorithm or data structure, "
        "why it is more efficient than the brute force, and its time and space complexity. No code."
    ),
}


def get_first_prompt(step: str) -> str:
    return _FIRST_PROMPTS[step]


def build_system_prompt() -> str:
    return SYSTEM_PROMPT


def build_grade_prompt(
    step: str,
    problem_title: str,
    problem_content: str,
    user_answer: str,
    reference_solution: str | None = None,
) -> str:
    content_snippet = problem_content[:3000]
    parts = [
        f"Step: {step}",
        _STEP_INSTRUCTIONS.get(step, ""),
        "",
        f"Problem: {problem_title}",
        content_snippet,
        "",
        "Candidate's answer:",
        user_answer,
    ]
    if step == "code" and reference_solution:
        parts += [
            "",
            "Reference solution (algorithmic equivalence check — not a literal match requirement):",
            reference_solution,
        ]
    return "\n".join(parts)


def build_hint_prompt(
    step: str,
    hint_number: int,
    problem_title: str,
    problem_content: str,
    previous_answers: list[str],
) -> str:
    level = min(hint_number, 3)
    specificity = _HINT_SPECIFICITY[level]

    prev = ""
    if previous_answers:
        attempts = "\n".join(f"  - {a}" for a in previous_answers[-2:])
        prev = f"\nThe candidate's previous attempt(s) at this step:\n{attempts}\n"

    return (
        f"You are a helpful coding interview coach.\n"
        f"The candidate is stuck on the '{step}' step. This is hint #{hint_number}.\n\n"
        f"{specificity}\n"
        f"Keep your hint to 3-5 sentences. Do NOT reveal the complete solution or write code.\n"
        f"\nProblem: {problem_title}\n{problem_content[:2000]}"
        f"{prev}"
    )


def build_step_solution_prompt(
    step: str,
    problem_title: str,
    problem_content: str,
) -> str:
    focus = _STEP_SOLUTION_FOCUS[step]
    return (
        f"{focus}\n"
        f"Keep your explanation to 4-6 sentences.\n"
        f"\nProblem: {problem_title}\n{problem_content[:2000]}"
    )


def build_explain_prompt(
    question: str,
    problem_title: str,
    problem_content: str,
    reference_solution: str,
) -> str:
    return (
        f"You are a patient and educational coding interview coach.\n"
        f"A student has a follow-up question about a LeetCode problem and its solution.\n"
        f"Answer clearly and educationally. Use concrete examples where helpful.\n"
        f"Match your depth to the question — a line-level question needs 2-3 sentences; "
        f"a broad 'explain the whole thing' question deserves a thorough walkthrough.\n\n"
        f"Problem: {problem_title}\n{problem_content[:2000]}\n\n"
        f"Reference solution:\n```python\n{reference_solution[:1500]}\n```\n\n"
        f"Student's question: {question}"
    )


REFERENCE_SOLUTION_PROMPT = """\
Generate an optimal, clean Python solution for the following LeetCode problem.
Include only the code; you may add brief inline comments explaining key steps.
Do not include any prose outside the code.

Problem: {title}

{content}
"""
