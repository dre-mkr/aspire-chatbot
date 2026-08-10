"""Does the semantic cache's 0.95 threshold separate paraphrases from neighbours?"""

from __future__ import annotations

import asyncio
import itertools
import math

from app.cache import _shelf_vector  # the exact truncation the shelf applies
from app.config import get_settings
from app.rag import get_embeddings

#: Paraphrase clusters: every pair inside a cluster wants the SAME answer.
PARAPHRASES = [
    [
        "What is the ASPIRE Programme?",
        "what is aspire programme",
        "Tell me about the ASPIRE programme",
        "Can you explain what ASPIRE is?",
        "que es el programa ASPIRE",
    ],
    [
        "How do I open an ASPIRE savings account?",
        "How can I open a savings account with ASPIRE?",
        "What do I do to open an ASPIRE account?",
    ],
    [
        "What is interest?",
        "Can you explain interest to me?",
        "what does interest mean",
    ],
]

#: Distinct questions: every pair here wants a DIFFERENT answer.
DISTINCT = [
    "What is the ASPIRE Programme?",
    "How do I open an ASPIRE savings account?",
    "What is interest?",
    "Who is eligible for ASPIRE?",
    "What is ASPIRE Day?",
    "How much money is in an ASPIRE account?",
    "What is a budget?",
    "Why do people invest?",
]

#: The pairs a wrong hit harms most: one fact apart, close in wording.
ADVERSARIAL = [
    ("Can I withdraw money at 16?", "Can I withdraw money at 18?"),
    ("How much can I deposit each month?", "How much can I withdraw each month?"),
    ("Is ASPIRE for children aged 5 to 18?", "Is ASPIRE for children aged 5 to 12?"),
    ("Can my parents see my ASPIRE account?", "Can my teachers see my ASPIRE account?"),
    ("What happens to my account when I turn 18?", "What happens to my account when I turn 16?"),
    ("¿Puedo retirar dinero a los 16?", "¿Puedo retirar dinero a los 18?"),
]


def _cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb)


async def main() -> None:
    threshold = get_settings().semantic_cache_threshold
    backend = get_embeddings()

    texts: list[str] = sorted(
        {q for cluster in PARAPHRASES for q in cluster}
        | set(DISTINCT)
        | {q for pair in ADVERSARIAL for q in pair}
    )
    print(f"embedding {len(texts)} questions...")
    vectors = {text: await backend.aembed_query(text) for text in texts}
    shelves = {text: _shelf_vector(vector) for text, vector in vectors.items()}

    def report(name: str, pairs: list[tuple[str, str]], want_hit: bool) -> list[float]:
        full = [_cos(vectors[a], vectors[b]) for a, b in pairs]
        cut = [_cos(shelves[a], shelves[b]) for a, b in pairs]
        wrong_full = sum(1 for c in full if (c >= threshold) != want_hit)
        wrong_cut = sum(1 for c in cut if (c >= threshold) != want_hit)
        print(f"\n{name} (n={len(pairs)}, want {'HIT' if want_hit else 'MISS'} at {threshold}):")
        print(f"  full 3072d: min={min(full):.4f} max={max(full):.4f} misclassified={wrong_full}")
        print(f"  shelf dims: min={min(cut):.4f} max={max(cut):.4f} misclassified={wrong_cut}")
        for (a, b), c_full, c_cut in zip(pairs, full, cut):
            flag_full = "HIT " if c_full >= threshold else "miss"
            flag_cut = "HIT " if c_cut >= threshold else "miss"
            marker = ""
            if (c_cut >= threshold) != want_hit:
                marker = "   <-- WRONG at shelf dims"
            elif (c_full >= threshold) != want_hit:
                marker = "   <-- wrong at full dims only"
            print(f"    {c_full:.4f}/{flag_full}  {c_cut:.4f}/{flag_cut}  {a!r} ~ {b!r}{marker}")
        return cut

    paraphrase_pairs = [
        pair for cluster in PARAPHRASES for pair in itertools.combinations(cluster, 2)
    ]
    distinct_pairs = list(itertools.combinations(DISTINCT, 2))

    para = report("PARAPHRASES", paraphrase_pairs, want_hit=True)
    dist = report("DISTINCT", distinct_pairs, want_hit=False)
    adv = report("ADVERSARIAL", ADVERSARIAL, want_hit=False)

    print("\n--- verdict ---")
    print(f"threshold: {threshold}")
    print(f"paraphrases served from cache at shelf dims: {sum(1 for c in para if c >= threshold)}/{len(para)}")
    print(f"distinct questions wrongly served:           {sum(1 for c in dist if c >= threshold)}/{len(dist)}")
    print(f"adversarial near-pairs wrongly served:       {sum(1 for c in adv if c >= threshold)}/{len(adv)}")
    highest_unsafe = max(max(dist), max(adv))
    print(f"highest unsafe cosine at shelf dims: {highest_unsafe:.4f} "
          f"(margin to threshold: {threshold - highest_unsafe:+.4f})")


if __name__ == "__main__":
    asyncio.run(main())
