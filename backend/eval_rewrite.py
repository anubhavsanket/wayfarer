"""Benchmark bullet rewrite quality: lfm2.5-thinking vs llama3.2:3b.

Tests tricky cases where rewrite quality matters most:
- Ambiguous skill mapping
- Metrics preservation
- Natural language flow
- Domain-specific terminology
"""
import asyncio
import httpx
import json
import sys
import time

# Fix Windows encoding for print
sys.stdout.reconfigure(encoding='utf-8')

OLLAMA_URL = "http://localhost:11434/api/chat"

TEST_CASES = [
    {
        "name": "metric_preservation",
        "keyword": "system design",
        "original": "Built a real-time recommendation engine serving 10k requests/day with p99 latency under 50ms using Python and Redis",
        "prompt_template": (
            "Rewrite the following resume bullet to incorporate the JD keyword "
            "naturally, WITHOUT changing any facts, metrics, or exaggerating.\n\n"
            "JD KEYWORD: {keyword}\n"
            "ORIGINAL BULLET: {original}\n\n"
            "Return ONLY the rewritten bullet text, nothing else."
        ),
    },
    {
        "name": "ambiguous_skill_mapping",
        "keyword": "cloud infrastructure",
        "original": "Deployed ML models on AWS EC2 with auto-scaling groups and CloudWatch monitoring",
        "prompt_template": (
            "Rewrite the following resume bullet to incorporate the JD keyword "
            "naturally, WITHOUT changing any facts, metrics, or exaggerating.\n\n"
            "JD KEYWORD: {keyword}\n"
            "ORIGINAL BULLET: {original}\n\n"
            "Return ONLY the rewritten bullet text, nothing else."
        ),
    },
    {
        "name": "technical_terminology",
        "keyword": "MLOps",
        "original": "Built CI/CD pipelines for model training using GitHub Actions and DVC for version control",
        "prompt_template": (
            "Rewrite the following resume bullet to incorporate the JD keyword "
            "naturally, WITHOUT changing any facts, metrics, or exaggerating.\n\n"
            "JD KEYWORD: {keyword}\n"
            "ORIGINAL BULLET: {original}\n\n"
            "Return ONLY the rewritten bullet text, nothing else."
        ),
    },
    {
        "name": "soft_skill_incorporation",
        "keyword": "cross-functional collaboration",
        "original": "Worked with product and data teams to prioritize ML features based on business impact",
        "prompt_template": (
            "Rewrite the following resume bullet to incorporate the JD keyword "
            "naturally, WITHOUT changing any facts, metrics, or exaggerating.\n\n"
            "JD KEYWORD: {keyword}\n"
            "ORIGINAL BULLET: {original}\n\n"
            "Return ONLY the rewritten bullet text, nothing else."
        ),
    },
    {
        "name": "framework_swap",
        "keyword": "PyTorch",
        "original": "Trained a BERT-based sentiment classifier achieving 94% accuracy on internal dataset using TensorFlow",
        "prompt_template": (
            "Rewrite the following resume bullet to incorporate the JD keyword "
            "naturally, WITHOUT changing any facts, metrics, or exaggerating.\n\n"
            "JD KEYWORD: {keyword}\n"
            "ORIGINAL BULLET: {original}\n\n"
            "Return ONLY the rewritten bullet text, nothing else."
        ),
    },
    {
        "name": "conciseness_under_pressure",
        "keyword": "RAG",
        "original": "Designed and implemented a retrieval-augmented generation pipeline that indexed 50k documents using ChromaDB vector store, with a FastAPI backend serving queries in under 200ms p95",
        "prompt_template": (
            "Rewrite the following resume bullet to incorporate the JD keyword "
            "naturally, WITHOUT changing any facts, metrics, or exaggerating.\n\n"
            "JD KEYWORD: {keyword}\n"
            "ORIGINAL BULLET: {original}\n\n"
            "Return ONLY the rewritten bullet text, nothing else."
        ),
    },
]


async def call_ollama(model: str, prompt: str) -> tuple[str, float]:
    """Call Ollama and return (response, time_seconds)."""
    start = time.time()
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(OLLAMA_URL, json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": 0.2, "num_predict": 256},
        })
        elapsed = time.time() - start
        data = resp.json()
        content = data.get("message", {}).get("content", "")
        return content.strip(), elapsed


def evaluate_rewrite(original: str, keyword: str, rewrite: str) -> dict:
    """Simple heuristic evaluation of rewrite quality."""
    issues = []

    # Check 1: Does it contain the keyword?
    if keyword.lower() not in rewrite.lower():
        issues.append(f"MISSING_KEYWORD: '{keyword}' not in rewrite")

    # Check 2: Is it significantly shorter? (might have dropped content)
    if len(rewrite) < len(original) * 0.5:
        issues.append(f"TOO_SHORT: {len(rewrite)} chars vs {len(original)} original")

    # Check 3: Is it significantly longer? (might be hallucinating)
    if len(rewrite) > len(original) * 2:
        issues.append(f"TOO_LONG: {len(rewrite)} chars vs {len(original)} original")

    # Check 4: Does it still contain numbers/metrics from original?
    import re
    orig_numbers = set(re.findall(r"\d+", original))
    rewrite_numbers = set(re.findall(r"\d+", rewrite))
    missing_numbers = orig_numbers - rewrite_numbers
    if missing_numbers:
        issues.append(f"MISSING_NUMBERS: {missing_numbers} dropped")

    # Check 5: Is it just the original with keyword stuffed in?
    orig_words = set(original.lower().split())
    rewrite_words = set(rewrite.lower().split())
    overlap = len(orig_words & rewrite_words) / max(1, len(orig_words))
    if overlap > 0.9 and keyword.lower() not in original.lower():
        issues.append("KEYWORD_STUFF: mostly original text with keyword appended")

    return {
        "issues": issues,
        "score": 1.0 - (len(issues) * 0.2),
        "length": len(rewrite),
    }


async def run_benchmark():
    """Run all test cases on both models and compare."""
    models = ["lfm2.5-thinking", "llama3.2:3b"]

    # Check which models are available
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get("http://localhost:11434/api/tags")
        available = {m["name"].split(":")[0] for m in resp.json().get("models", [])}

    print(f"Available models: {available}")
    models = [m for m in models if m.split(":")[0] in available or m in available]
    print(f"Testing models: {models}\n")

    if len(models) < 2:
        print("Need at least 2 models to compare. Pull the missing one:")
        print("  docker compose exec ollama ollama pull lfm2.5-thinking")
        print("  docker compose exec ollama ollama pull llama3.2:3b")
        return

    results = {m: [] for m in models}

    for case in TEST_CASES:
        print(f"--- {case['name']} ---")
        print(f"  Original: {case['original'][:80]}...")
        print(f"  Keyword:  {case['keyword']}")

        for model in models:
            prompt = case["prompt_template"].format(
                keyword=case["keyword"], original=case["original"]
            )
            try:
                rewrite, elapsed = await call_ollama(model, prompt)
                eval_result = evaluate_rewrite(case["original"], case["keyword"], rewrite)
                results[model].append({
                    "case": case["name"],
                    "rewrite": rewrite,
                    "elapsed": elapsed,
                    **eval_result,
                })
                score_icon = "✅" if eval_result["score"] >= 0.8 else "⚠️" if eval_result["score"] >= 0.6 else "❌"
                print(f"  {model}: {score_icon} {eval_result['score']:.1%} ({elapsed:.1f}s)")
                print(f"    → {rewrite[:100]}")
                if eval_result["issues"]:
                    print(f"    Issues: {', '.join(eval_result['issues'])}")
            except Exception as exc:
                print(f"  {model}: ERROR — {exc}")
                results[model].append({
                    "case": case["name"], "rewrite": "", "elapsed": 0,
                    "issues": [str(exc)], "score": 0, "length": 0,
                })

        print()

    # Summary
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for model in models:
        scores = [r["score"] for r in results[model]]
        times = [r["elapsed"] for r in results[model]]
        avg_score = sum(scores) / len(scores) if scores else 0
        avg_time = sum(times) / len(times) if times else 0
        min_score = min(scores) if scores else 0
        print(f"{model:20s}  avg_score={avg_score:.1%}  min={min_score:.1%}  avg_time={avg_time:.1f}s")

    # Determine verdict
    lfm_scores = [r["score"] for r in results.get("lfm2.5-thinking", [])]
    llama_scores = [r["score"] for r in results.get("llama3.2:3b", [])]
    if lfm_scores and llama_scores:
        lfm_avg = sum(lfm_scores) / len(lfm_scores)
        llama_avg = sum(llama_scores) / len(llama_scores)
        diff = lfm_avg - llama_avg
        if diff >= -0.05:  # lfm is within 5% of llama
            print(f"\n✅ VERDICT: lfm2.5-thinking is within 5% of llama3.2:3b on rewrites")
            print(f"   Safe to use for both tiers.")
        else:
            print(f"\n⚠️ VERDICT: lfm2.5-thinking is {abs(diff):.1%} below llama3.2:3b on rewrites")
            print(f"   Keep complex tier on llama3.2:3b for bullet rewrites.")


if __name__ == "__main__":
    asyncio.run(run_benchmark())
