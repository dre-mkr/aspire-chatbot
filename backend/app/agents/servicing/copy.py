"""What to tell someone asking about their own account.

Deliberately free of app imports so `main_graph` can hold this as its
registration-failure fallback without an import cycle.
"""

from __future__ import annotations

from typing import Final

#: There is no balance in this system to look up, and pretending otherwise
#: would be the only dishonest answer available. Three real places hold what
#: the reader is asking for: quarterly valuation statements are published, the
#: portal shows account activity, the bank holds the account. All three are in
#: the corpus. Naming them IS the answer, not a deflection from it.
ACCOUNT_ELSEWHERE: Final[dict[str, str]] = {
    "en": (
        "I cannot see anyone's account from here — balances and statements are "
        "not something this assistant holds. Your ASPIRE savings are at the "
        "St. Kitts-Nevis-Anguilla National Bank, participants receive quarterly "
        "valuation statements, and account activity is on the ASPIRE portal at "
        "aspire.gov.kn. For anything the portal does not answer — a payment that "
        "has not arrived, a detail that needs changing — the ASPIRE team is the "
        "right place: aspire@gov.kn, +1 (869) 667-5566, or +1 (869) 762-1947. "
        "Is there something about the programme itself I can help with?"
    ),
    "es": (
        "No puedo ver la cuenta de nadie desde aquí: este asistente no tiene "
        "saldos ni estados de cuenta. Los ahorros de ASPIRE están en el "
        "St. Kitts-Nevis-Anguilla National Bank, los participantes reciben "
        "estados de valoración trimestrales, y la actividad de la cuenta está en "
        "el portal de ASPIRE, aspire.gov.kn. Para lo que el portal no resuelva "
        "— un pago que no ha llegado, un dato que hay que cambiar — el equipo de "
        "ASPIRE es el lugar: aspire@gov.kn, +1 (869) 667-5566 o "
        "+1 (869) 762-1947. ¿Puedo ayudarte con algo del programa en sí?"
    ),
    "fr": (
        "Je ne peux voir le compte de personne d'ici : cet assistant ne détient "
        "ni soldes ni relevés. L'épargne ASPIRE se trouve à la "
        "St. Kitts-Nevis-Anguilla National Bank, les participants reçoivent des "
        "relevés d'évaluation trimestriels, et l'activité du compte est sur le "
        "portail ASPIRE, aspire.gov.kn. Pour ce que le portail ne règle pas — un "
        "paiement qui n'est pas arrivé, une information à modifier — l'équipe "
        "ASPIRE est la bonne adresse : aspire@gov.kn, +1 (869) 667-5566 ou "
        "+1 (869) 762-1947. Puis-je vous aider sur le programme lui-même ?"
    ),
}

#: Somewhere to go next, so an account question is not a dead end.
CHIPS: Final[dict[str, list[str]]] = {
    "en": ["About the programme", "Talk to the team"],
    "es": ["Sobre el programa", "Hablar con el equipo"],
    "fr": ["À propos du programme", "Parler à l'équipe"],
}


#: The same answer for a reader whose word cap cannot hold the long one.
#:
#: A guardian's cap follows their CHILD's band, so the parent of a six-year-old
#: is capped at 35 words. The full answer is 88, and truncation took the reply
#: apart in the worst possible order: the apology survived and the bank, the
#: portal, the email and both phone numbers -- the entire answer -- were cut.
#:
#: So the short form drops the portal and the second number rather than let the
#: truncator choose. What a parent chasing a missing payment actually needs is
#: one address and one number, and those are what fit.
ACCOUNT_ELSEWHERE_BRIEF: Final[dict[str, str]] = {
    "en": (
        "I cannot see accounts from here. ASPIRE savings are held at the "
        "National Bank, and statements come every quarter. For anything else "
        "the ASPIRE team can help: aspire@gov.kn or +1 (869) 667-5566."
    ),
    "es": (
        "No puedo ver cuentas desde aquí. Los ahorros de ASPIRE están en el "
        "National Bank y los estados llegan cada trimestre. Para lo demás, el "
        "equipo de ASPIRE ayuda: aspire@gov.kn o +1 (869) 667-5566."
    ),
    "fr": (
        "Je ne peux pas voir les comptes d'ici. L'épargne ASPIRE est à la "
        "National Bank et les relevés arrivent chaque trimestre. Pour le reste, "
        "l'équipe ASPIRE aide : aspire@gov.kn ou +1 (869) 667-5566."
    ),
}
