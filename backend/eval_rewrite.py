"""Benchmark bullet rewrite quality across 4 local models.

Expanded eval set (20 cases) covering diverse rewrite scenarios:
- Short bullets, long bullets, metric-heavy, soft skills, technical terms
- Edge cases: framework swaps, role transitions, domain jargon

Models: qwen3:1.7b, llama3.2:3b, qwen2.5:1.5b, lfm2.5-thinking
Max tokens: 2048, with /no_think for qwen3
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
    # === Original 6 ===
    {"name": "metric_preservation", "keyword": "system design",
     "original": "Built a real-time recommendation engine serving 10k requests/day with p99 latency under 50ms using Python and Redis"},
    {"name": "ambiguous_skill_mapping", "keyword": "cloud infrastructure",
     "original": "Deployed ML models on AWS EC2 with auto-scaling groups and CloudWatch monitoring"},
    {"name": "technical_terminology", "keyword": "MLOps",
     "original": "Built CI/CD pipelines for model training using GitHub Actions and DVC for version control"},
    {"name": "soft_skill_incorporation", "keyword": "cross-functional collaboration",
     "original": "Worked with product and data teams to prioritize ML features based on business impact"},
    {"name": "framework_swap", "keyword": "PyTorch",
     "original": "Trained a BERT-based sentiment classifier achieving 94% accuracy on internal dataset using TensorFlow"},
    {"name": "conciseness_under_pressure", "keyword": "RAG",
     "original": "Designed and implemented a retrieval-augmented generation pipeline that indexed 50k documents using ChromaDB vector store, with a FastAPI backend serving queries in under 200ms p95"},
    # === Extended cases ===
    {"name": "multi_metric", "keyword": "data pipeline",
     "original": "Reduced data processing time from 4 hours to 15 minutes by implementing parallel ETL pipelines with Apache Airflow, processing 2M records daily"},
    {"name": "short_bullet", "keyword": "Docker",
     "original": "Containerized microservices"},
    {"name": "long_bullet", "keyword": "Kubernetes",
     "original": "Designed and implemented a production-grade Kubernetes deployment strategy for a 12-microservice architecture including blue-green deployments, canary releases, horizontal pod autoscaling based on custom metrics, and Istio service mesh for traffic management and mTLS"},
    {"name": "role_transition", "keyword": "technical leadership",
     "original": "Mentored 3 junior engineers through code reviews and pair programming sessions, resulting in 2 promotions within 6 months"},
    {"name": "domain_jargon", "keyword": "feature store",
     "original": "Built a centralized feature store using Feast to manage 200+ ML features across training and serving pipelines with point-in-time correctness"},
    {"name": "quantitative", "keyword": "cost optimization",
     "original": "Optimized AWS infrastructure reducing monthly cloud spend from $15k to $8k through right-sizing instances, implementing spot fleets, and consolidating redundant services"},
    {"name": "comparison", "keyword": "A/B testing",
     "original": "Designed A/B testing framework that ran 50 concurrent experiments measuring user engagement metrics with statistical significance testing"},
    {"name": "integration", "keyword": "event-driven architecture",
     "original": "Migrated batch processing system to event-driven architecture using Apache Kafka, reducing data latency from hours to seconds for 10 downstream consumers"},
    {"name": "security", "keyword": "zero trust",
     "original": "Implemented role-based access control for internal ML platform using OAuth2 and RBAC policies, serving 50+ data scientists"},
    {"name": "monitoring", "keyword": "observability",
     "original": "Set up comprehensive monitoring with Prometheus and Grafana tracking 200+ metrics across 15 services with automated alerting"},
    {"name": "performance", "keyword": "latency optimization",
     "original": "Optimized model inference latency from 500ms to 45ms p99 through ONNX Runtime quantization and dynamic batching"},
    {"name": "data_quality", "keyword": "data governance",
     "original": "Implemented data validation pipeline using Great Expectations catching 15% of incoming records with schema violations before training"},
    {"name": "migration", "keyword": "platform migration",
     "original": "Led migration of 40+ ML models from manual Jupyter notebook deployment to automated MLflow pipelines, reducing deployment time from 2 days to 30 minutes"},
    {"name": "collaboration", "keyword": "stakeholder communication",
     "original": "Presented weekly ML pipeline health reports to VP of Engineering, translating technical metrics into business-relevant KPIs"},
    {"name": "edge_case", "keyword": "edge computing",
     "original": "Deployed lightweight TFLite models to edge devices for real-time object detection at 30fps on Raspberry Pi 4"},
]

PROMPT = (
    "Rewrite the following resume bullet to incorporate the JD keyword "
    "naturally, WITHOUT changing any facts, metrics, or exaggerating.\n\n"
    "JD KEYWORD: {keyword}\n"
    "ORIGINAL BULLET: {original}\n\n"
    "Return ONLY the rewritten bullet text, nothing else."
)

MAX_TOKENS = 2048


async def call_ollama(model: str, prompt: str) -> tuple[str, float, dict]:
    """Call Ollama. For qwen3, prepend /no_think to suppress reasoning trace."""
    # Prepend /no_think for qwen3 thinking models
    if "qwen3" in model.lower():
        prompt = "/no_think\n" + prompt

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
        }
        return content.strip(), elapsed, info


def evaluate_rewrite(original: str, keyword: str, rewrite: str) -> dict:
    issues = []
    if not rewrite:
        issues.append("EMPTY")
        return {"issues": issues, "score": 0.0, "length": 0}
    if keyword.lower() not in rewrite.lower():
        issues.append("MISSING_KW")
    if len(rewrite) < len(original) * 0.4:
        issues.append("SHORT")
    if len(rewrite) > len(original) * 2.5:
        issues.append("LONG")
    orig_nums = set(re.findall(r"\d+", original))
    rew_nums = set(re.findall(r"\d+", rewrite))
    if orig_nums - rew_nums:
        issues.append("MISS_NUM")
    return {"issues": issues, "score": max(0, 1.0 - len(issues) * 0.2), "length": len(rewrite)}


async def run_benchmark():
    models = ["qwen3:1.7b", "llama3.2:3b", "qwen2.5:1.5b", "lfm2.5-thinking"]

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get("http://localhost:11434/api/tags")
        available = {m["name"].split(":")[0] for m in resp.json().get("models", [])}
    models = [m for m in models if m.split(":")[0] in available or m in available]

    print(f"Models: {models}")
    print(f"Cases: {len(TEST_CASES)}")
    print(f"Max tokens: {MAX_TOKENS}\n")

    results = {m: [] for m in models}

    for i, case in enumerate(TEST_CASES):
        print(f"[{i+1:2d}/{len(TEST_CASES)}] {case['name']}", end=" ")
        for model in models:
            prompt = PROMPT.format(keyword=case["keyword"], original=case["original"])
            try:
                rewrite, elapsed, info = await call_ollama(model, prompt)
                ev = evaluate_rewrite(case["original"], case["keyword"], rewrite)
                results[model].append({"case": case["name"], "rewrite": rewrite, "elapsed": elapsed, **ev, **info})
                mark = "+" if ev["score"] >= 0.8 else "~" if ev["score"] >= 0.6 else "-"
                print(f"{model[:8]}:{mark}", end=" ")
            except Exception as exc:
                results[model].append({"case": case["name"], "rewrite": "", "elapsed": 0,
                                       "issues": [str(exc)], "score": 0, "length": 0, "eval_count": 0})
                print(f"{model[:8]}:!", end=" ")
        print()

    # Summary
    print(f"\n{'=' * 90}")
    print(f"{'Model':20s}  {'Avg':>5s}  {'Min':>5s}  {'Median':>7s}  {'Time':>7s}  {'Tokens':>7s}  {'Empty':>6s}  {'<60%':>5s}")
    print(f"{'=' * 90}")
    for model in models:
        scores = sorted([r["score"] for r in results[model]])
        times = [r["elapsed"] for r in results[model]]
        tokens = [r.get("eval_count", 0) for r in results[model]]
        empties = sum(1 for r in results[model] if not r.get("rewrite"))
        low = sum(1 for s in scores if s < 0.6)
        n = len(scores)
        avg = sum(scores) / n if n else 0
        mn = min(scores) if n else 0
        med = scores[n // 2] if n else 0
        avg_t = sum(times) / n if n else 0
        avg_tok = sum(tokens) / n if n else 0
        print(f"{model:20s}  {avg:4.0%}  {mn:4.0%}  {med:6.0%}  {avg_t:5.1f}s  {avg_tok:6.0f}  {empties:5d}  {low:4d}")

    # Pairwise
    baseline = "llama3.2:3b"
    if baseline in models:
        b_scores = sorted([r["score"] for r in results[baseline]])
        b_avg = sum(b_scores) / len(b_scores)
        print(f"\nvs {baseline} baseline ({b_avg:.0%}):")
        for model in models:
            if model == baseline: continue
            m_scores = [r["score"] for r in results[model]]
            m_avg = sum(m_scores) / len(m_scores) if m_scores else 0
            d = m_avg - b_avg
            print(f"  {model:20s}  {m_avg:.0%}  ({d:+.0%})")


if __name__ == "__main__":
    asyncio.run(run_benchmark())
