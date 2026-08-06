"""Check non-determinism: run the same benchmark twice, compare results."""
import asyncio
import httpx
import json
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

VALID_LEVELS = {'fresher', 'junior', 'mid', 'senior', 'unclear'}
SYNONYM_MAP = {'entry-level': 'junior', 'entry level': 'junior', 'mid-level': 'mid', 'beginner': 'fresher'}

CASES = [
    ('explicit_senior', 'Senior ML Engineer with 7+ years of experience', 'senior'),
    ('explicit_junior', 'Junior Python Developer, 1-2 years experience preferred', 'junior'),
    ('explicit_fresher', 'Fresh graduates welcome, no prior experience required', 'fresher'),
    ('explicit_mid', 'Mid-level Data Engineer, 3-5 years of experience with Python and SQL', 'mid'),
    ('implicit_senior', 'Lead the design and architecture of distributed systems serving millions of users', 'senior'),
    ('implicit_junior', 'Entry-level position, will learn on the job with mentorship', 'junior'),
    ('year_range_1_3', 'Looking for someone with 1-3 years of software development experience', 'junior'),
    ('year_range_5_plus', 'Requires 5+ years of experience in machine learning or data science', 'senior'),
    ('ambiguous_no_years', 'Join our growing AI team to build production ML pipelines', 'unclear'),
    ('tricky_mid_senior', 'Staff Engineer — responsible for technical direction across the ML platform', 'senior'),
    ('tricky_fresh_grad', 'Recent graduates with strong fundamentals in CS and ML welcome', 'fresher'),
    ('tricky_intern', 'Summer internship, paid, for students pursuing CS degrees', 'fresher'),
    ('lead_role', 'Engineering Manager leading a team of 8 ML engineers', 'senior'),
    ('vp_level', 'VP of Engineering, 15+ years experience, P&L ownership', 'senior'),
    ('no_experience_hint', 'Full stack developer needed for React and Node.js projects', 'unclear'),
    ('years_explicit_2', 'Minimum 2 years of experience with cloud platforms (AWS/GCP)', 'junior'),
    ('years_explicit_4', '4 years of professional experience in software engineering required', 'mid'),
    ('years_explicit_8', '8+ years in data engineering with Spark and Hadoop ecosystems', 'senior'),
    ('graduate_program', 'Graduate rotation program - rotate across 4 teams in 18 months', 'fresher'),
    ('principal_engineer', 'Principal Software Engineer, deep expertise in distributed systems', 'senior'),
]


async def classify_one(text):
    prompt = f'/no_think\nClassify: {text}. JSON: experience_level'
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post('http://localhost:11434/api/chat', json={
            'model': 'qwen2.5:1.5b',
            'messages': [{'role': 'user', 'content': prompt}],
            'stream': False,
            'options': {'num_predict': 256, 'temperature': 0.1}
        })
    c = resp.json().get('message', {}).get('content', '')
    try:
        m = re.search(r'\{[^}]+\}', c)
        if m:
            raw = json.loads(m.group()).get('experience_level', 'unclear').strip().lower()
            level = SYNONYM_MAP.get(raw, raw)
            if level not in VALID_LEVELS:
                for v in VALID_LEVELS:
                    if v in raw:
                        level = v
                        break
        else:
            level = 'unclear'
    except Exception:
        level = 'unclear'
    for v in VALID_LEVELS:
        if v in c.lower():
            level = v
            break
    return level, c


async def run_once(run_id):
    results = []
    correct = 0
    for name, text, expected in CASES:
        level, raw = await classify_one(text)
        ok = level == expected
        correct += ok
        results.append((name, expected, level, ok, raw[:80]))
    return correct, results


async def main():
    print("Run 1:")
    c1, r1 = await run_once(1)
    for name, exp, got, ok, raw in r1:
        print(f"  {name:25s} exp={exp:8s} got={got:8s} {'OK' if ok else 'WRONG'}")
    print(f"  Accuracy: {c1}/{len(CASES)} = {c1/len(CASES):.0%}\n")

    print("Run 2:")
    c2, r2 = await run_once(2)
    for name, exp, got, ok, raw in r2:
        print(f"  {name:25s} exp={exp:8s} got={got:8s} {'OK' if ok else 'WRONG'}")
    print(f"  Accuracy: {c2}/{len(CASES)} = {c2/len(CASES):.0%}\n")

    # Compare
    flipped = []
    for i, ((n1, e1, g1, ok1, _), (n2, e2, g2, ok2, _)) in enumerate(zip(r1, r2)):
        if ok1 != ok2:
            flipped.append((n1, e1, g1, g2))
    print(f"Determinism: {len(flipped)} cases flipped between runs")
    if flipped:
        for name, exp, g1, g2 in flipped:
            print(f"  {name}: run1={g1} run2={g2} (expected={exp})")


if __name__ == "__main__":
    asyncio.run(main())
