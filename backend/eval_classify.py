"""Benchmark experience classification across 3 models.

Tests tricky classification cases where the model must determine
experience level from JD text. Validates simple-tier model choice.
"""
import asyncio
import httpx
import json
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')

OLLAMA_URL = "http://localhost:11434/api/chat"

TEST_CASES = [
    {"name": "explicit_senior", "text": "Senior ML Engineer with 7+ years of experience in production ML systems", "expected": "senior"},
    {"name": "explicit_junior", "text": "Junior Python Developer, 1-2 years experience preferred", "expected": "junior"},
    {"name": "explicit_fresher", "text": "Fresh graduates welcome, no prior experience required", "expected": "fresher"},
    {"name": "explicit_mid", "text": "Mid-level Data Engineer, 3-5 years of experience with Python and SQL", "expected": "mid"},
    {"name": "implicit_senior", "text": "Lead the design and architecture of distributed systems serving millions of users", "expected": "senior"},
    {"name": "implicit_junior", "text": "Entry-level position, will learn on the job with mentorship", "expected": "junior"},
    {"name": "year_range_1_3", "text": "Looking for someone with 1-3 years of software development experience", "expected": "junior"},
    {"name": "year_range_5_plus", "text": "Requires 5+ years of experience in machine learning or data science", "expected": "senior"},
    {"name": "ambiguous_no_years", "text": "Join our growing AI team to build production ML pipelines", "expected": "unclear"},
    {"name": "tricky_mid_senior", "text": "Staff Engineer — responsible for technical direction across the ML platform", "expected": "senior"},
    {"name": "tricky_fresh_grad", "text": "Recent graduates with strong fundamentals in CS and ML welcome", "expected": "fresher"},
    {"name": "tricky_intern", "text": "Summer internship, paid, for students pursuing CS degrees", "expected": "fresher"},
    {"name": "lead_role", "text": "Engineering Manager leading a team of 8 ML engineers", "expected": "senior"},
    {"name": "vp_level", "text": "VP of Engineering, 15+ years experience, P&L ownership", "expected": "senior"},
    {"name": "no_experience_hint", "text": "Full stack developer needed for React and Node.js projects", "expected": "unclear"},
    {"name": "years_explicit_2", "text": "Minimum 2 years of experience with cloud platforms (AWS/GCP)", "expected": "junior"},
    {"name": "years_explicit_4", "text": "4 years of professional experience in software engineering required", "expected": "mid"},
    {"name": "years_explicit_8", "text": "8+ years in data engineering with Spark and Hadoop ecosystems", "expected": "senior"},
    {"name": "graduate_program", "text": "Graduate rotation program — rotate across 4 teams in 18 months", "expected": "fresher"},
    {"name": "principal_engineer", "text": "Principal Software Engineer, deep expertise in distributed systems", "expected": "senior"},
]

VALID_LEVELS = {"fresher", "junior", "mid", "senior", "unclear"}

PROMPT = """Classify the experience level required by this job posting.

Rules:
- "fresher": 0-1 years, entry-level, graduate, freshers welcome
- "junior": 1-3 years
- "mid": 3-5 years
- "senior": 5+ years, lead, principal, staff
- "unclear": no clear experience requirement stated

Job posting:
{text}

Return ONLY a JSON object with keys: experience_level, min_experience_years, confidence"""


async def call_ollama(model: str, prompt: str) -> tuple[str, float]:
    start = time.time()
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(OLLAMA_URL, json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 256},
        })
        elapsed = time.time() - start
        content = resp.json().get("message", {}).get("content", "")
        return content.strip(), elapsed


def parse_classification(response: str) -> str:
    """Extract experience_level from model response."""
    try:
        # Try to find JSON in response
        import re
        match = re.search(r'\{[^}]+\}', response)
        if match:
            data = json.loads(match.group())
            level = data.get("experience_level", "unclear").lower()
            if level in VALID_LEVELS:
                return level
    except (json.JSONDecodeError, AttributeError):
        pass

    # Fallback: check for keywords
    lower = response.lower()
    for level in VALID_LEVELS:
        if level in lower:
            return level
    return "unclear"


async def run_benchmark():
    models = ["qwen3:1.7b", "lfm2.5-thinking", "qwen2.5:1.5b"]

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get("http://localhost:11434/api/tags")
        available = {m["name"].split(":")[0] for m in resp.json().get("models", [])}
    models = [m for m in models if m.split(":")[0] in available or m in available]

    print(f"Models: {models}")
    print(f"Cases: {len(TEST_CASES)}")
    print()

    results = {m: [] for m in models}

    for i, case in enumerate(TEST_CASES):
        print(f"[{i+1:2d}/{len(TEST_CASES)}] {case['name']:25s} expected={case['expected']:8s}", end=" ")
        for model in models:
            prompt = PROMPT.format(text=case["text"])
            # Prepend /no_think for qwen3
            if "qwen3" in model.lower():
                prompt = "/no_think\n" + prompt
            try:
                response, elapsed = await call_ollama(model, prompt)
                predicted = parse_classification(response)
                correct = predicted == case["expected"]
                results[model].append({
                    "case": case["name"],
                    "expected": case["expected"],
                    "predicted": predicted,
                    "correct": correct,
                    "elapsed": elapsed,
                })
                mark = "+" if correct else "X"
                print(f"{model[:10]}:{mark}({predicted})", end=" ")
            except Exception as exc:
                results[model].append({
                    "case": case["name"], "expected": case["expected"],
                    "predicted": "error", "correct": False, "elapsed": 0,
                })
                print(f"{model[:10]}:!", end=" ")
        print()

    # Summary
    print(f"\n{'=' * 80}")
    print(f"{'Model':20s}  {'Accuracy':>10s}  {'Correct':>8s}  {'Wrong':>6s}  {'Avg Time':>10s}")
    print(f"{'=' * 80}")
    for model in models:
        correct = sum(1 for r in results[model] if r["correct"])
        total = len(results[model])
        wrong = total - correct
        avg_time = sum(r["elapsed"] for r in results[model]) / total if total else 0
        acc = correct / total if total else 0
        print(f"{model:20s}  {acc:9.0%}  {correct:7d}  {wrong:5d}  {avg_time:8.1f}s")

    # Per-category breakdown
    print(f"\n{'=' * 80}")
    print("ERROR ANALYSIS")
    print("=" * 80)
    for model in models:
        wrong = [r for r in results[model] if not r["correct"]]
        if wrong:
            print(f"\n{model} errors:")
            for r in wrong:
                print(f"  {r['case']:25s}  expected={r['expected']:8s}  got={r['predicted']:8s}")
        else:
            print(f"\n{model}: no errors")


if __name__ == "__main__":
    asyncio.run(run_benchmark())
