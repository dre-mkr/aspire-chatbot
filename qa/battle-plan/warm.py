import sys, time, statistics
sys.path.insert(0, '.')
from harness import fresh
r = fresh("warm")
qs = ["What is ASPIRE?", "Who can join ASPIRE?", "What is compound interest?"]
for q in qs:
    t = r.say(q)
    print(f"{t.elapsed_ms:6d}ms  ttfb={t.first_token_ms}  agent={t.agent}  len={len(t.text)}  q={q[:30]}")
r.close()
