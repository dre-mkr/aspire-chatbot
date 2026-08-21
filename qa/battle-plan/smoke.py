import sys, json
sys.path.insert(0, '.')
from harness import fresh

r = fresh("smoke")
print("persona:", r.persona, "band:", r.age_band, "status:", r.account_status)
t = r.say("What is ASPIRE?")
print("agent:", t.agent, "status:", t.status, "ms:", t.elapsed_ms, "ttfb:", t.first_token_ms)
print("error:", t.error)
print("TEXT:", (t.text or "")[:700])
print("directives:", [d.get("type") for d in t.directives])
r.close()
