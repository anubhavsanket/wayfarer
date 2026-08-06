"""Benchmark bullet rewrite quality across 4 local models.

Tests tricky cases where rewrite quality matters most:
- Ambiguous skill mapping
- Metrics preservation
- Natural language flow
- Domain-specific terminology

Models: lfm2.5-thinking, llama3.2:3b, qwen3:1.7b, qwen2.5:1.5b
Max tokens: 2048 (enough for thinking model reasoning traces)
"""
import asyncio
import httpx
import json
import sys
import time
import re

sys.stdout.reconfigure(encoding='utf-8')

OLLAMA_URL = "http://localhost:11434/api/chat"

TEST_CASES = [
    {
        "name": "metric_preservation",
        "keyword": "system design",
        "original": "Built a real-time recommendation engine serving 10k requests/day with p99 latency under 50ms using Python and Redis",
    },
    {
        "name": "ambiguous_skill_mapping",
        "keyword": "cloud infrastructure",
        "original": "Deployed ML models on AWS EC2 with auto-scaling groups and CloudWatch monitoring",
    },
    {
        "name": "technical_terminology",
        "keyword": "MLOps",
        "original": "Built CI/CD pipelines for model training using GitHub Actions and DVC for version control",
    },
    {
        "name": "soft_skill_incorporation",
        "keyword": "cross-functional collaboration",
        "original": "Worked with product and data teams to prioritize ML features based on business impact",
    },
    {
        "name": "framework_swap",
        "keyword": "PyTorch",
        "original": "Trained a BERT-based sentiment classifier achieving 94% accuracy on internal dataset using TensorFlow",
    },
    {
        "name": "conciseness_under_pressure",
        "keyword": "RAG",
        "original": "Designed and implemented a retrieval-augmented generation pipeline that indexed 50k documents using ChromaDB vector store, with a FastAPI backend serving queries in under 200ms p95",
    },
]

PROMPT = (
    "Rewrite the following resume bullet to incorporate the JD keyword "
    "naturally, WITHOUT changing any facts, metrics, or exaggerating.\n\n"
    "JD KEYWORD: {keyword}\n"
    "ORIGINAL BULLET: {original}\n\n"
    "Return ONLY the rewritten bullet text, nothing else."
)

MAX_TOKENS = 2048  # Enough for thinking model reasoning traces


async def call_ollama(model: str, prompt: str) -> tuple[str, float, dict]:
    """Call Ollama and return (response, time_seconds, raw_info)."""
    start = time.time()
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(OLLAMA_URL, json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": 0.2, "num_predict": MAX_TOKENS},
        })
        elapsed = time.time() - start
        data = resp.json()
        content = data.get("message", {}).get("content", "")
        info = {
            "eval_count": data.get("eval_count", 0),
            "prompt_eval_count": data.get("prompt_eval_count", 0),
            "total_duration": data.get("total_duration", 0) / 1e9,
        }
        return content.strip(), elapsed, info


def evaluate_rewrite(original: str, keyword: str, rewrite: str) -> dict:
    """Evaluate rewrite quality."""
    issues = []

    if not rewrite:
        issues.append("EMPTY_RESPONSE")
        return {"issues": issues, "score": 0.0, "length": 0}

    if keyword.lower() not in rewrite.lower():
        issues.append(f"MISSING_KEYWORD")

    if len(rewrite) < len(original) * 0.5:
        issues.append(f"TOO_SHORT")

    if len(rewrite) > len(original) * 2:
        issues.append(f"TOO_LONG")

    orig_numbers = set(re.findall(r"\d+", original))
    rewrite_numbers = set(re.findall(r"\d+", rewrite))
    missing_numbers = orig_numbers - rewrite_numbers
    if missing_numbers:
        issues.append(f"MISSING_NUMBERS:{missing_numbers}")

    return {
        "issues": issues,
        "score": max(0, 1.0 - (len(issues) * 0.2)),
        "length": len(rewrite),
    }


async def run_benchmark():
    """Run all test cases on all models and compare."""
    models = ["lfm2.5-thinking", "llama3.2:3b", "qwen3:1.7b", "qwen2.5:1.5b"]

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get("http://localhost:11434/api/tags")
        available = {m["name"].split(":")[0] for m in resp.json().get("models", [])}

    models = [m for m in models if m.split(":")[0] in available or m in available]
    print(f"Models: {models}")
    print(f"Max tokens per response: {MAX_TOKENS}\n")

    results = {m: [] for m in models}

    for case in TEST_CASES:
        print(f"--- {case['name']} ---")
        print(f"  Original: {case['original'][:80]}...")
        print(f"  Keyword:  {case['keyword']}")

        for model in models:
            prompt = PROMPT.format(keyword=case["keyword"], original=case["original"])
            try:
                rewrite, elapsed, info = await call_ollama(model, prompt)
                eval_result = evaluate_rewrite(case["original"], case["keyword"], rewrite)
                results[model].append({
                    "case": case["name"],
                    "rewrite": rewrite,
                    "elapsed": elapsed,
                    **eval_result,
                    **info,
                })
                score_icon = "+" if eval_result["score"] >= 0.8 else "~" if eval_result["score"] >= 0.6 else "-"
                print(f"  {model:20s} [{score_icon}] {eval_result['score']:.0%} ({elapsed:.1f}s, {info['eval_count']}tok)")
                print(f"    {rewrite[:120] if rewrite else '(empty)'}")
                if eval_result["issues"]:
                    print(f"    Issues: {', '.join(eval_result['issues'])}")
            except Exception as exc:
                print(f"  {model:20s} [!] ERROR: {exc}")
                results[model].append({"case": case["name"], "rewrite": "", "elapsed": 0,
                                       "issues": [str(exc)], "score": 0, "length": 0,
                                       "eval_count": 0, "prompt_eval_count": 0, "total_duration": 0})
        print()

    # Summary table
    print("=" * 80)
    print(f"{'Model':20s}  {'Avg Score':>10s}  {'Min':>5s}  {'Avg Time':>10s}  {'Avg Tokens':>11s}  {'Empty':>6s}")
    print("=" * 80)
    for model in models:
        scores = [r["score"] for r in results[model]]
        times = [r["elapsed"] for r in results[model]]
        tokens = [r.get("eval_count", 0) for r in results[model]]
        empties = sum(1 for r in results[model] if not r.get("rewrite"))
        avg_score = sum(scores) / len(scores) if scores else 0
        min_score = min(scores) if scores else 0
        avg_time = sum(times) / len(times) if times else 0
        avg_tokens = sum(tokens) / len(tokens) if tokens else 0
        print(f"{model:20s}  {avg_score:9.1%}  {min_score:4.0%}  {avg_time:8.1f}s  {avg_tokens:10.0f}  {empties:5d}")

    # Pairwise comparison
    if len(models) >= 2:
        print(f"\n{'=' * 80}")
        print("PAIRWISE COMPARISON (vs llama3.2:3b baseline)")
        print("=" * 80)
        baseline = "llama3.2:3b"
        if baseline not in models:
            baseline = models[0]
        baseline_scores = [r["score"] for r in results[baseline]]
        baseline_avg = sum(baseline_scores) / len(baseline_scores) if baseline_scores else 0
        print(f"Baseline: {baseline} (avg {baseline_avg:.1%})\n")

        for model in models:
            if model == baseline:
                continue
            model_scores = [r["score"] for r in results[model]]
            model_avg = sum(model_scores) / len(model_scores) if model_scores else 0
            diff = model_avg - baseline_avg
            marker = "CLOSE" if abs(diff) <= 0.05 else "BELOW" if diff < 0 else "ABOVE"
            print(f"  {model:20s}  {model_avg:.1%}  ({diff:+.1%})  [{marker}]")


if __name__ == "__main__":
    asyncio.run(run_benchmark())
