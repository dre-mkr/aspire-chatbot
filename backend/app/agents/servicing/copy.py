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
