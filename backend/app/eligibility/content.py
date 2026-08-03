"""Every word this flow says, in English, Spanish and French.

Copy lives apart from `rules.py` on purpose. The rules decide *which* verdict;
this decides how it reads. That split is what lets the wording be reviewed by
someone who is not reading Python, and it is why adding a language is this file
only.

Three constraints hold across all three languages, and the tests check them:

1. **Nothing here decides anything.** No string asserts a criterion that
   `rules.py` does not hold, and `rules.py` cites a knowledge-base row for every
   one it holds.
2. **No approval language.** "You are approved", "accepted", "you qualify" flat
   — none of these appear in any language. The strongest available phrasing is
   "based on what you have told me, you will likely qualify".
3. **The hedges survive translation.** Where the source says "confirm the
   current document list at aspire.gov.kn", every language says it too. A
   document list that reads as settled in French and provisional in English is
   the same defect as inventing one.

French and Spanish run roughly 20-30% longer than English. The card is built to
absorb that; the copy is still kept as tight as it can be without losing the
hedge, because the hedge is the part that must not be cut to fit.
"""

from __future__ import annotations

from app.eligibility.models import Language

# Contact details, identical in every language because they are not words.
# ASP-208, ASP-209, ASP-328.
EMAIL = "aspire@gov.kn"
PHONES = ("+1 (869) 667-5566", "+1 (869) 762-1947")
HOTLINE = "465-2588"
PORTAL_URL = "https://portal.aspire.gov.kn/register"
SITE_URL = "https://aspire.gov.kn"

# The one on-screen walk-in centre the knowledge base names, and its hours.
# ASP-299, ASP-300 -- both `as_of` 2025-07-08, which is why the copy tells
# people to confirm before travelling rather than presenting the hours as fact.
CABLE_OFFICE = "The Cable Office, Cayon Street, Basseterre"
CABLE_HOURS = "Mon-Fri, 9:00 AM - 3:00 PM"


# --- Questions ------------------------------------------------------------
#
# Keyed by question id, then language. Option labels are keyed by the token the
# engine stores; the token is never shown and never translated.

QUESTIONS: dict[str, dict[Language, dict[str, str]]] = {
    "age": {
        Language.EN: {
            "text": "How old are you, or the child you are asking about?",
            "help": "A range is enough. I never store your age.",
            "under5": "Under 5",
            "5to18": "5 to 18",
            "19to21": "19 to 21",
            "22plus": "22 or older",
            "unsure": "I am not sure",
        },
        Language.ES: {
            "text": "¿Qué edad tienes tú, o el niño o niña por quien preguntas?",
            "help": "Con un rango basta. Nunca guardo tu edad.",
            "under5": "Menos de 5",
            "5to18": "De 5 a 18",
            "19to21": "De 19 a 21",
            "22plus": "22 o más",
            "unsure": "No estoy seguro/a",
        },
        Language.FR: {
            "text": "Quel âge as-tu, ou l'enfant pour lequel tu poses la question ?",
            "help": "Une tranche suffit. Je n'enregistre jamais ton âge.",
            "under5": "Moins de 5 ans",
            "5to18": "De 5 à 18 ans",
            "19to21": "De 19 à 21 ans",
            "22plus": "22 ans ou plus",
            "unsure": "Je ne sais pas",
        },
    },
    # Asked only on the under-5 branch, and only so the result can name a year
    # instead of saying "later". Discarded with the session like everything else.
    "age_exact": {
        Language.EN: {
            "text": "How old are they right now?",
            "help": "This is only so I can tell you which year they can register.",
            "0": "Under 1",
            "1": "1",
            "2": "2",
            "3": "3",
            "4": "4",
            "unsure": "I am not sure",
        },
        Language.ES: {
            "text": "¿Qué edad tiene ahora mismo?",
            "help": "Solo es para decirte en qué año podrá inscribirse.",
            "0": "Menos de 1",
            "1": "1",
            "2": "2",
            "3": "3",
            "4": "4",
            "unsure": "No estoy seguro/a",
        },
        Language.FR: {
            "text": "Quel âge a-t-il ou a-t-elle en ce moment ?",
            "help": "C'est seulement pour te dire en quelle année l'inscription sera possible.",
            "0": "Moins de 1 an",
            "1": "1 an",
            "2": "2 ans",
            "3": "3 ans",
            "4": "4 ans",
            "unsure": "Je ne sais pas",
        },
    },
    "citizenship": {
        Language.EN: {
            "text": "Are they a citizen of Saint Kitts and Nevis?",
            "help": "Citizens by descent count, including those born abroad.",
            "born_skn": "Yes, born in the Federation",
            "by_descent": "Yes, a citizen by descent",
            "neither": "No, neither of those",
            "unsure": "I am not sure",
        },
        Language.ES: {
            "text": "¿Es ciudadano o ciudadana de San Cristóbal y Nieves?",
            "help": "La ciudadanía por descendencia cuenta, incluso si nació fuera del país.",
            "born_skn": "Sí, nació en la Federación",
            "by_descent": "Sí, por descendencia",
            "neither": "No, ninguna de las dos",
            "unsure": "No estoy seguro/a",
        },
        Language.FR: {
            "text": "Est-il ou elle citoyen(ne) de Saint-Christophe-et-Niévès ?",
            "help": "La citoyenneté par filiation compte, même en cas de naissance à l'étranger.",
            "born_skn": "Oui, né(e) dans la Fédération",
            "by_descent": "Oui, par filiation",
            "neither": "Non, ni l'un ni l'autre",
            "unsure": "Je ne sais pas",
        },
    },
    "residence": {
        Language.EN: {
            "text": "Where do they live right now?",
            "help": "Both islands are covered in exactly the same way.",
            "st_kitts": "St. Kitts",
            "nevis": "Nevis",
            "abroad": "Outside the Federation",
            "unsure": "I am not sure",
        },
        Language.ES: {
            "text": "¿Dónde vive actualmente?",
            "help": "Las dos islas están cubiertas exactamente igual.",
            "st_kitts": "San Cristóbal",
            "nevis": "Nieves",
            "abroad": "Fuera de la Federación",
            "unsure": "No estoy seguro/a",
        },
        Language.FR: {
            "text": "Où habite-t-il ou elle en ce moment ?",
            "help": "Les deux îles sont couvertes exactement de la même façon.",
            "st_kitts": "Saint-Christophe",
            "nevis": "Niévès",
            "abroad": "Hors de la Fédération",
            "unsure": "Je ne sais pas",
        },
    },
    "school": {
        Language.EN: {
            "text": "Are they in school in the Federation?",
            "help": "Home schooling registered with the Ministry of Education counts.",
            "in_school": "Yes, at a school here",
            "home_school": "Home schooled, registered with the Ministry",
            "not_in_school": "Not in school right now",
            "unsure": "I am not sure",
        },
        Language.ES: {
            "text": "¿Está estudiando en la Federación?",
            "help": "La educación en casa registrada con el Ministerio de Educación cuenta.",
            "in_school": "Sí, en una escuela de aquí",
            "home_school": "En casa, registrado con el Ministerio",
            "not_in_school": "Ahora mismo no estudia",
            "unsure": "No estoy seguro/a",
        },
        Language.FR: {
            "text": "Est-il ou elle scolarisé(e) dans la Fédération ?",
            "help": "L'école à la maison déclarée au ministère de l'Éducation compte.",
            "in_school": "Oui, dans une école d'ici",
            "home_school": "À la maison, déclaré(e) au ministère",
            "not_in_school": "Pas scolarisé(e) en ce moment",
            "unsure": "Je ne sais pas",
        },
    },
    "registrant": {
        Language.EN: {
            "text": "Who will fill in the registration form?",
            "help": "This only changes the paperwork, never whether they can join.",
            "guardian": "A parent or guardian",
            "self": "I will, for myself",
            "unsure": "I am not sure yet",
        },
        Language.ES: {
            "text": "¿Quién va a llenar el formulario de inscripción?",
            "help": "Esto solo cambia los papeles, nunca si puede participar.",
            "guardian": "Un padre, madre o tutor",
            "self": "Yo mismo/a",
            "unsure": "Todavía no lo sé",
        },
        Language.FR: {
            "text": "Qui va remplir le formulaire d'inscription ?",
            "help": "Cela ne change que les documents, jamais le droit de participer.",
            "guardian": "Un parent ou tuteur",
            "self": "Moi-même",
            "unsure": "Je ne sais pas encore",
        },
    },
}


# --- Chrome ---------------------------------------------------------------

UI: dict[Language, dict[str, str]] = {
    Language.EN: {
        "title": "ASPIRE eligibility check",
        "subtitle": "A quick pre-check, not an application",
        "progress": "Question {position} of {total}",
        "back": "Back",
        "leave": "Ask something else",
        "close": "Close",
        "restart": "Start the check again",
        "checklist_heading": "What to bring",
        "steps_heading": "How to apply",
        "checked_note": "Tick these off as you gather them. Saved on this device only.",
        "where_label": "Where",
        "signed_label": "Signed by",
        "contact_heading": "Who to ask",
        # Shown on the card the whole way through, not in fine print.
        "banner": "This is a pre-check, not a decision on an application.",
    },
    Language.ES: {
        "title": "Consulta de elegibilidad de ASPIRE",
        "subtitle": "Una consulta rápida, no una solicitud",
        "progress": "Pregunta {position} de {total}",
        "back": "Atrás",
        "leave": "Preguntar otra cosa",
        "close": "Cerrar",
        "restart": "Empezar la consulta de nuevo",
        "checklist_heading": "Qué llevar",
        "steps_heading": "Cómo inscribirse",
        "checked_note": "Márcalos según los reúnas. Se guardan solo en este dispositivo.",
        "where_label": "Dónde",
        "signed_label": "Quién lo firma",
        "contact_heading": "A quién preguntar",
        "banner": "Esto es una consulta previa, no una decisión sobre una solicitud.",
    },
    Language.FR: {
        "title": "Vérification d'admissibilité ASPIRE",
        "subtitle": "Une vérification rapide, pas une candidature",
        "progress": "Question {position} sur {total}",
        "back": "Retour",
        "leave": "Poser une autre question",
        "close": "Fermer",
        "restart": "Recommencer la vérification",
        "checklist_heading": "Ce qu'il faut apporter",
        "steps_heading": "Comment s'inscrire",
        "checked_note": "Coche-les au fur et à mesure. Enregistré sur cet appareil uniquement.",
        "where_label": "Où",
        "signed_label": "Signé par",
        "contact_heading": "À qui s'adresser",
        "banner": "Ceci est une vérification préalable, pas une décision sur une candidature.",
    },
}


# --- Results --------------------------------------------------------------
#
# `headline` never states a decision. `body` is a tuple of short paragraphs.
# `{year}` is substituted only on the under-5 branch.

RESULTS: dict[str, dict[Language, dict[str, object]]] = {
    "likely_eligible": {
        Language.EN: {
            "headline": "Based on what you have told me, you will likely qualify",
            "body": (
                "Everything you have said matches what ASPIRE asks for: citizenship, "
                "age, living in the Federation, and being in school.",
                "ASPIRE decides applications, not me. The list below is what to have "
                "ready when you register.",
            ),
        },
        Language.ES: {
            "headline": "Según lo que me has contado, es probable que cumpla los requisitos",
            "body": (
                "Todo lo que has dicho coincide con lo que pide ASPIRE: ciudadanía, "
                "edad, vivir en la Federación y estar estudiando.",
                "Las solicitudes las decide ASPIRE, no yo. La lista de abajo es lo "
                "que conviene tener listo al inscribirse.",
            ),
        },
        Language.FR: {
            "headline": "D'après ce que tu m'as dit, l'admissibilité est probable",
            "body": (
                "Tout ce que tu as indiqué correspond à ce que demande ASPIRE : "
                "citoyenneté, âge, résidence dans la Fédération et scolarisation.",
                "C'est ASPIRE qui décide des candidatures, pas moi. La liste ci-dessous "
                "indique ce qu'il faut préparer pour l'inscription.",
            ),
        },
    },
    # The under-5 branch. The single most important piece of copy in the flow:
    # it is a "not yet" that has to read as a date in the diary, not a refusal.
    "age_minimum": {
        Language.EN: {
            "headline": "Not yet — but there is a date to put in the diary",
            "body": (
                "ASPIRE starts at age 5. Registration is open all year round, and "
                "children are enrolled as they reach their fifth birthday.",
                "So nothing is missed by waiting: there is no deadline and no queue.",
            ),
            "year": "That means registration can happen from around {year}.",
            "meanwhile": (
                "In the meantime, ask me anything about how the savings account, the "
                "shares, or the money side of ASPIRE works."
            ),
        },
        Language.ES: {
            "headline": "Todavía no, pero ya hay una fecha para anotar",
            "body": (
                "ASPIRE empieza a los 5 años. La inscripción está abierta todo el año "
                "y los niños se inscriben al cumplir los cinco.",
                "Así que no se pierde nada por esperar: no hay fecha límite ni fila.",
            ),
            "year": "Es decir, la inscripción se podrá hacer a partir de {year}, más o menos.",
            "meanwhile": (
                "Mientras tanto, pregúntame lo que quieras sobre la cuenta de ahorros, "
                "las acciones o cómo funciona el dinero en ASPIRE."
            ),
        },
        Language.FR: {
            "headline": "Pas encore, mais il y a une date à noter",
            "body": (
                "ASPIRE commence à 5 ans. Les inscriptions sont ouvertes toute l'année "
                "et les enfants sont inscrits dès leur cinquième anniversaire.",
                "Rien n'est donc perdu à attendre : il n'y a ni date limite ni file d'attente.",
            ),
            "year": "L'inscription sera donc possible à partir de {year} environ.",
            "meanwhile": (
                "En attendant, pose-moi toutes tes questions sur le compte d'épargne, "
                "les actions, ou le fonctionnement de l'argent dans ASPIRE."
            ),
        },
    },
    # Citizenship is the one firm "no" in the source (ASP-039). It still never
    # reads as a rejection of the person.
    "citizenship": {
        Language.EN: {
            "headline": "ASPIRE is only open to citizens of Saint Kitts and Nevis",
            "body": (
                "The programme is limited to citizens, whether born in the Federation "
                "or citizens by descent. Permanent residents are not included.",
                "If there is any chance of a claim to citizenship by descent — a parent "
                "or grandparent born here — that is worth checking with the ASPIRE team "
                "before ruling it out.",
            ),
            "meanwhile": (
                "Everything else I know about saving, investing and money is still "
                "yours to ask about, whoever you are."
            ),
        },
        Language.ES: {
            "headline": "ASPIRE es solo para ciudadanos de San Cristóbal y Nieves",
            "body": (
                "El programa está limitado a ciudadanos, ya sea por nacimiento en la "
                "Federación o por descendencia. Los residentes permanentes no entran.",
                "Si existe alguna posibilidad de ciudadanía por descendencia —un padre, "
                "madre o abuelo nacido aquí—, vale la pena confirmarlo con el equipo de "
                "ASPIRE antes de descartarlo.",
            ),
            "meanwhile": (
                "Todo lo demás que sé sobre ahorrar, invertir y el dinero sigue estando "
                "a tu disposición, seas quien seas."
            ),
        },
        Language.FR: {
            "headline": "ASPIRE est réservé aux citoyens de Saint-Christophe-et-Niévès",
            "body": (
                "Le programme est limité aux citoyens, nés dans la Fédération ou "
                "citoyens par filiation. Les résidents permanents n'y ont pas droit.",
                "S'il existe une possibilité de citoyenneté par filiation — un parent ou "
                "grand-parent né ici — cela vaut la peine de le vérifier auprès de "
                "l'équipe ASPIRE avant d'abandonner.",
            ),
            "meanwhile": (
                "Tout ce que je sais sur l'épargne, l'investissement et l'argent reste "
                "à ta disposition, quelle que soit ta situation."
            ),
        },
    },
    # 22+. Outside both the 5-18 band and, on any ordinary birthdate, the
    # 13 December 2023 cohort clause. The clause is still surfaced, because we
    # asked for a band and not a date.
    "age_cohort_past": {
        Language.EN: {
            "headline": "ASPIRE's initial seeding is for a defined group of young people",
            "body": (
                "The programme covers young people aged 5 to 18, plus those who were "
                "18 or under on 13 December 2023.",
                "I asked for an age range rather than a birthday, so if you were 18 or "
                "under on that date it is worth asking the ASPIRE team directly — they "
                "hold the final word on the cohort.",
            ),
            "meanwhile": (
                "If you have a child of your own who is 5 or older, they can be "
                "registered — ask me and I will run the check for them."
            ),
        },
        Language.ES: {
            "headline": "La aportación inicial de ASPIRE es para un grupo determinado de jóvenes",
            "body": (
                "El programa cubre a jóvenes de 5 a 18 años, además de quienes tenían "
                "18 años o menos el 13 de diciembre de 2023.",
                "Te pedí un rango de edad y no una fecha de nacimiento, así que si en "
                "esa fecha tenías 18 o menos, conviene preguntar directamente al equipo "
                "de ASPIRE: ellos tienen la última palabra sobre el grupo.",
            ),
            "meanwhile": (
                "Si tienes un hijo o hija de 5 años o más, sí se puede inscribir: "
                "pídemelo y hago la consulta para él o ella."
            ),
        },
        Language.FR: {
            "headline": "La dotation initiale d'ASPIRE vise un groupe précis de jeunes",
            "body": (
                "Le programme couvre les jeunes de 5 à 18 ans, ainsi que ceux qui "
                "avaient 18 ans ou moins le 13 décembre 2023.",
                "J'ai demandé une tranche d'âge et non une date de naissance : si tu "
                "avais 18 ans ou moins à cette date, il vaut la peine de contacter "
                "l'équipe ASPIRE, qui tranche sur la composition du groupe.",
            ),
            "meanwhile": (
                "Si tu as un enfant de 5 ans ou plus, il peut être inscrit : demande-le "
                "moi et je fais la vérification pour lui."
            ),
        },
    },
    "needs_confirmation": {
        Language.EN: {
            "headline": "Almost there — one thing I cannot settle from here",
            "body": (
                "Nothing you told me rules ASPIRE out. There is just a point the "
                "programme's own published information does not answer, and I will not "
                "guess at it.",
                "The ASPIRE team can settle it in a minute. Here is the question to put "
                "to them:",
            ),
        },
        Language.ES: {
            "headline": "Casi — hay algo que no puedo resolver desde aquí",
            "body": (
                "Nada de lo que me has dicho descarta ASPIRE. Solo hay un punto que la "
                "información publicada del programa no responde, y no voy a suponerlo.",
                "El equipo de ASPIRE lo resuelve en un minuto. Esta es la pregunta que "
                "conviene hacerles:",
            ),
        },
        Language.FR: {
            "headline": "Presque — un point que je ne peux pas trancher d'ici",
            "body": (
                "Rien de ce que tu m'as dit n'exclut ASPIRE. Il reste seulement un point "
                "auquel les informations publiées du programme ne répondent pas, et je "
                "ne vais pas le deviner.",
                "L'équipe ASPIRE peut le régler en une minute. Voici la question à leur "
                "poser :",
            ),
        },
    },
}


# The pre-check disclaimer, repeated under the verdict where it cannot be
# missed. Distinct from the running banner, and deliberately not softer.
DISCLAIMER: dict[Language, str] = {
    Language.EN: (
        "This is a pre-check based only on what you told me. It is not an "
        "application, not a decision, and not a promise. Only ASPIRE can confirm "
        "an application."
    ),
    Language.ES: (
        "Esta es una consulta previa basada solo en lo que me has contado. No es "
        "una solicitud, ni una decisión, ni una promesa. Solo ASPIRE puede "
        "confirmar una solicitud."
    ),
    Language.FR: (
        "Ceci est une vérification préalable fondée uniquement sur ce que tu m'as "
        "dit. Ce n'est ni une candidature, ni une décision, ni une promesse. Seul "
        "ASPIRE peut confirmer une candidature."
    ),
}


# Pre-framed questions for the mentor, one per unresolvable criterion. Written
# so the person can read them out or paste them into an email unchanged.
MENTOR_QUESTIONS: dict[str, dict[Language, str]] = {
    "age_cohort": {
        Language.EN: (
            "I am over 18 now, but I may have been 18 or under on 13 December 2023. "
            "Does the ASPIRE cohort still cover me?"
        ),
        Language.ES: (
            "Ahora tengo más de 18 años, pero puede que el 13 de diciembre de 2023 "
            "tuviera 18 o menos. ¿Me sigue cubriendo el grupo de ASPIRE?"
        ),
        Language.FR: (
            "J'ai plus de 18 ans aujourd'hui, mais j'avais peut-être 18 ans ou moins "
            "le 13 décembre 2023. Suis-je encore couvert par le groupe ASPIRE ?"
        ),
    },
    "citizenship": {
        Language.EN: (
            "I am not sure whether my child counts as a citizen by descent. What "
            "should I check, and which certificate would I need?"
        ),
        Language.ES: (
            "No estoy seguro/a de si mi hijo o hija cuenta como ciudadano por "
            "descendencia. ¿Qué debo comprobar y qué certificado haría falta?"
        ),
        Language.FR: (
            "Je ne sais pas si mon enfant est citoyen par filiation. Que dois-je "
            "vérifier, et quel certificat faudrait-il ?"
        ),
    },
    "residence": {
        Language.EN: (
            "We are citizens but currently living outside the Federation. Can we "
            "register for ASPIRE now, or do we need to be resident first?"
        ),
        Language.ES: (
            "Somos ciudadanos pero vivimos fuera de la Federación. ¿Podemos "
            "inscribirnos en ASPIRE ahora o hay que residir en el país primero?"
        ),
        Language.FR: (
            "Nous sommes citoyens mais vivons hors de la Fédération. Pouvons-nous "
            "nous inscrire à ASPIRE maintenant, ou faut-il d'abord y résider ?"
        ),
    },
    "school": {
        Language.EN: (
            "My child is not enrolled in school at the moment. Can they still "
            "register for ASPIRE, or do they need to be enrolled first?"
        ),
        Language.ES: (
            "Mi hijo o hija no está matriculado en la escuela ahora mismo. ¿Puede "
            "inscribirse igualmente en ASPIRE o hay que matricularlo primero?"
        ),
        Language.FR: (
            "Mon enfant n'est pas scolarisé en ce moment. Peut-il quand même "
            "s'inscrire à ASPIRE, ou faut-il d'abord une inscription scolaire ?"
        ),
    },
    "age_minimum": {
        Language.EN: (
            "I am not certain of my child's exact age. From what date can they be "
            "registered for ASPIRE?"
        ),
        Language.ES: (
            "No sé con certeza la edad exacta de mi hijo o hija. ¿A partir de qué "
            "fecha se puede inscribir en ASPIRE?"
        ),
        Language.FR: (
            "Je ne connais pas l'âge exact de mon enfant. À partir de quelle date "
            "peut-il être inscrit à ASPIRE ?"
        ),
    },
}


# What each unresolved criterion is called when several are listed together.
UNRESOLVED_LABELS: dict[str, dict[Language, str]] = {
    "age_cohort": {
        Language.EN: "Whether the 13 December 2023 cohort still covers this age",
        Language.ES: "Si el grupo del 13 de diciembre de 2023 cubre esta edad",
        Language.FR: "Si le groupe du 13 décembre 2023 couvre encore cet âge",
    },
    "age_minimum": {
        Language.EN: "The exact age, and the date registration can start",
        Language.ES: "La edad exacta y la fecha en que se puede inscribir",
        Language.FR: "L'âge exact et la date à laquelle l'inscription peut commencer",
    },
    "citizenship": {
        Language.EN: "Whether citizenship by descent applies",
        Language.ES: "Si aplica la ciudadanía por descendencia",
        Language.FR: "Si la citoyenneté par filiation s'applique",
    },
    "residence": {
        Language.EN: "Registering while living outside the Federation",
        Language.ES: "Inscribirse viviendo fuera de la Federación",
        Language.FR: "S'inscrire en vivant hors de la Fédération",
    },
    "school": {
        Language.EN: "Registering while not currently enrolled in school",
        Language.ES: "Inscribirse sin estar matriculado ahora mismo",
        Language.FR: "S'inscrire sans être scolarisé actuellement",
    },
}


# --- Documents ------------------------------------------------------------
#
# `where` never claims a civil-registry address: the knowledge base does not
# carry one, so it routes to the support channels it DOES carry. See the audit.

DOCUMENTS: dict[str, dict[Language, dict[str, str]]] = {
    # ASP-035, ASP-036. Firm.
    "birth_certificate": {
        Language.EN: {
            "title": "The child's Saint Kitts and Nevis birth certificate",
            "detail": "This is what proves citizenship for a child born in the Federation.",
            "where": (
                f"If you are not sure where to get a copy, the ASPIRE team will tell you: "
                f"{EMAIL}, hotline {HOTLINE}, or walk in to {CABLE_OFFICE}."
            ),
        },
        Language.ES: {
            "title": "Partida de nacimiento de San Cristóbal y Nieves del niño o niña",
            "detail": "Es lo que acredita la ciudadanía de un niño nacido en la Federación.",
            "where": (
                f"Si no sabes dónde conseguir una copia, el equipo de ASPIRE te lo dirá: "
                f"{EMAIL}, línea directa {HOTLINE}, o acude a {CABLE_OFFICE}."
            ),
        },
        Language.FR: {
            "title": "L'acte de naissance de Saint-Christophe-et-Niévès de l'enfant",
            "detail": "C'est ce qui prouve la citoyenneté d'un enfant né dans la Fédération.",
            "where": (
                f"Si tu ne sais pas où en obtenir une copie, l'équipe ASPIRE te le dira : "
                f"{EMAIL}, ligne directe {HOTLINE}, ou rends-toi à {CABLE_OFFICE}."
            ),
        },
    },
    # ASP-028, ASP-035, ASP-038. Firm.
    "descent_certificate": {
        Language.EN: {
            "title": "The citizenship by descent certificate",
            "detail": "This is the proof of citizenship for a child who is a citizen by descent.",
            "where": (
                f"The ASPIRE team can point you to it: {EMAIL} or hotline {HOTLINE}."
            ),
        },
        Language.ES: {
            "title": "Certificado de ciudadanía por descendencia",
            "detail": "Es la prueba de ciudadanía de un niño que lo es por descendencia.",
            "where": (
                f"El equipo de ASPIRE te puede orientar: {EMAIL} o línea directa {HOTLINE}."
            ),
        },
        Language.FR: {
            "title": "Le certificat de citoyenneté par filiation",
            "detail": "C'est la preuve de citoyenneté d'un enfant citoyen par filiation.",
            "where": (
                f"L'équipe ASPIRE peut t'orienter : {EMAIL} ou ligne directe {HOTLINE}."
            ),
        },
    },
    # ASP-250 says a passport showing a St. Kitts or Nevis birthplace qualifies;
    # ASP-037 hedges the same point. Offered as an alternative, never alone.
    "passport": {
        Language.EN: {
            "title": "Or a valid passport showing a St. Kitts or Nevis birthplace",
            "detail": "This has been accepted as identification in place of a birth certificate.",
            "where": f"Confirm which documents are being accepted at {SITE_URL} before you travel.",
            "caveat": "The published guidance is not consistent on this one — check first.",
        },
        Language.ES: {
            "title": "O un pasaporte válido que indique nacimiento en San Cristóbal o Nieves",
            "detail": "Se ha aceptado como identificación en lugar de la partida de nacimiento.",
            "where": f"Confirma qué documentos se aceptan en {SITE_URL} antes de desplazarte.",
            "caveat": "La información publicada no es consistente en este punto: confírmalo antes.",
        },
        Language.FR: {
            "title": "Ou un passeport valide indiquant une naissance à Saint-Christophe ou Niévès",
            "detail": "Il a été accepté comme pièce d'identité à la place de l'acte de naissance.",
            "where": f"Vérifie les documents acceptés sur {SITE_URL} avant de te déplacer.",
            "caveat": "Les informations publiées ne sont pas cohérentes sur ce point : vérifie d'abord.",
        },
    },
    # ASP-248. Stated, then hedged by the source itself.
    "guardian_id": {
        Language.EN: {
            "title": "The parent or guardian's identification",
            "detail": "The adult completing the form brings their own ID as well as the child's documents.",
            "where": f"Any question about which ID counts: {EMAIL} or hotline {HOTLINE}.",
            "signed_by": "The parent or legal guardian filling in the form",
            "caveat": f"Confirm the current document list at {SITE_URL}.",
        },
        Language.ES: {
            "title": "Identificación del padre, madre o tutor",
            "detail": "El adulto que llena el formulario lleva su propia identificación además de los documentos del niño.",
            "where": f"Cualquier duda sobre qué identificación vale: {EMAIL} o línea directa {HOTLINE}.",
            "signed_by": "El padre, madre o tutor legal que llena el formulario",
            "caveat": f"Confirma la lista actual de documentos en {SITE_URL}.",
        },
        Language.FR: {
            "title": "La pièce d'identité du parent ou tuteur",
            "detail": "L'adulte qui remplit le formulaire apporte sa propre pièce d'identité en plus des documents de l'enfant.",
            "where": f"Pour toute question sur les pièces acceptées : {EMAIL} ou ligne directe {HOTLINE}.",
            "signed_by": "Le parent ou tuteur légal qui remplit le formulaire",
            "caveat": f"Confirme la liste actuelle des documents sur {SITE_URL}.",
        },
    },
    # ASP-251. The weakest item in the source -- "registration MAY also ask".
    # Carried because turning up without it is the avoidable trip, but never
    # presented as required.
    "proof_of_address": {
        Language.EN: {
            "title": "Proof of address, dated within about three months",
            "detail": "A recent utility bill, bank statement, or lease agreement.",
            "where": f"Confirm whether this is being asked for at {SITE_URL}.",
            "caveat": "Registration may ask for this. It is not confirmed as required.",
        },
        Language.ES: {
            "title": "Comprobante de domicilio, de los últimos tres meses aproximadamente",
            "detail": "Un recibo de servicios reciente, un extracto bancario o un contrato de alquiler.",
            "where": f"Confirma si lo están pidiendo en {SITE_URL}.",
            "caveat": "La inscripción puede pedirlo. No está confirmado como obligatorio.",
        },
        Language.FR: {
            "title": "Un justificatif de domicile de moins de trois mois environ",
            "detail": "Une facture récente, un relevé bancaire ou un contrat de location.",
            "where": f"Vérifie si ce document est demandé sur {SITE_URL}.",
            "caveat": "L'inscription peut le demander. Ce n'est pas confirmé comme obligatoire.",
        },
    },
}


# --- Walkthrough ----------------------------------------------------------

STEPS: dict[str, dict[Language, dict[str, str]]] = {
    # ASP-045, ASP-046, ASP-292, ASP-294.
    "portal": {
        Language.EN: {
            "title": "Register online",
            "detail": f"Start at {SITE_URL} and open Register / Sign in. The Department of IT runs the portal.",
            "link_label": "Open the registration portal",
        },
        Language.ES: {
            "title": "Inscríbete en línea",
            "detail": f"Empieza en {SITE_URL} y abre Registrarse / Iniciar sesión. El Departamento de TI gestiona el portal.",
            "link_label": "Abrir el portal de inscripción",
        },
        Language.FR: {
            "title": "S'inscrire en ligne",
            "detail": f"Commence sur {SITE_URL} et ouvre Inscription / Connexion. Le Département informatique gère le portail.",
            "link_label": "Ouvrir le portail d'inscription",
        },
    },
    # ASP-295, ASP-049, ASP-050.
    "who_fills": {
        Language.EN: {
            "title": "Who fills in the form",
            "detail": (
                "A parent or legal guardian completes it for a child. From age 12, an "
                "ASPIRE participant can register for their own account."
            ),
        },
        Language.ES: {
            "title": "Quién llena el formulario",
            "detail": (
                "Un padre, madre o tutor legal lo completa por el niño. A partir de los "
                "12 años, un participante de ASPIRE puede inscribirse por su cuenta."
            ),
        },
        Language.FR: {
            "title": "Qui remplit le formulaire",
            "detail": (
                "Un parent ou tuteur légal le remplit pour l'enfant. Dès 12 ans, un "
                "participant ASPIRE peut créer son propre compte."
            ),
        },
    },
    # ASP-051, ASP-062.
    "documents": {
        Language.EN: {
            "title": "Have the documents ready",
            "detail": "The list above is what applies to your answers. Registration is free — ASPIRE charges nothing.",
        },
        Language.ES: {
            "title": "Ten los documentos listos",
            "detail": "La lista de arriba es la que corresponde a tus respuestas. La inscripción es gratuita: no se cobra nada.",
        },
        Language.FR: {
            "title": "Préparer les documents",
            "detail": "La liste ci-dessus correspond à tes réponses. L'inscription est gratuite : rien n'est facturé.",
        },
    },
    # ASP-299, ASP-300. St. Kitts only -- the source names no Nevis walk-in.
    "in_person_kitts": {
        Language.EN: {
            "title": "Or get help in person",
            "detail": (
                f"{CABLE_OFFICE} offers daily walk-in support, {CABLE_HOURS}. They can "
                "also edit an existing application or check its status. Hours were last "
                "published in July 2025 — worth a call first."
            ),
        },
        Language.ES: {
            "title": "O pide ayuda en persona",
            "detail": (
                f"{CABLE_OFFICE} ofrece atención sin cita todos los días, {CABLE_HOURS}. "
                "También pueden editar una solicitud existente o consultar su estado. El "
                "horario se publicó en julio de 2025: conviene llamar antes."
            ),
        },
        Language.FR: {
            "title": "Ou demander de l'aide sur place",
            "detail": (
                f"{CABLE_OFFICE} accueille sans rendez-vous, {CABLE_HOURS}. Le personnel "
                "peut aussi modifier une candidature existante ou vérifier son statut. "
                "Les horaires datent de juillet 2025 : mieux vaut appeler avant."
            ),
        },
    },
    # ASP-293, ASP-297, ASP-053, ASP-216. Used for Nevis, abroad, and unsure,
    # because the knowledge base names no walk-in centre outside Basseterre.
    "in_person_events": {
        Language.EN: {
            "title": "Or get help in person",
            "detail": (
                "The ASPIRE team visits primary and secondary schools across both "
                "islands during the school year, and runs sign-up help at ASPIRE Day and "
                "community events. The knowledge base names no permanent walk-in centre "
                f"outside Basseterre — ask {EMAIL} or hotline {HOTLINE} for dates near you."
            ),
        },
        Language.ES: {
            "title": "O pide ayuda en persona",
            "detail": (
                "El equipo de ASPIRE visita escuelas primarias y secundarias en las dos "
                "islas durante el curso, y ayuda con la inscripción en el Día de ASPIRE y "
                "en eventos comunitarios. No consta ningún centro permanente fuera de "
                f"Basseterre: escribe a {EMAIL} o llama al {HOTLINE} para saber las fechas."
            ),
        },
        Language.FR: {
            "title": "Ou demander de l'aide sur place",
            "detail": (
                "L'équipe ASPIRE visite les écoles primaires et secondaires des deux îles "
                "pendant l'année scolaire, et aide aux inscriptions lors de la Journée "
                "ASPIRE et d'événements communautaires. Aucun centre permanent hors de "
                f"Basseterre n'est répertorié : écris à {EMAIL} ou appelle le {HOTLINE}."
            ),
        },
    },
    # ASP-270, ASP-057.
    "after": {
        Language.EN: {
            "title": "What happens next",
            "detail": (
                "Completing registration starts the bank account opening. A seeded "
                "savings account is opened at the St. Kitts-Nevis-Anguilla National Bank "
                "and begins earning interest."
            ),
        },
        Language.ES: {
            "title": "Qué pasa después",
            "detail": (
                "Al completar la inscripción se inicia la apertura de la cuenta bancaria. "
                "Se abre una cuenta de ahorros con fondos iniciales en el St. Kitts-Nevis-"
                "Anguilla National Bank y empieza a generar intereses."
            ),
        },
        Language.FR: {
            "title": "Ce qui se passe ensuite",
            "detail": (
                "L'inscription terminée déclenche l'ouverture du compte bancaire. Un "
                "compte d'épargne doté est ouvert à la St. Kitts-Nevis-Anguilla National "
                "Bank et commence à produire des intérêts."
            ),
        },
    },
    # ASP-061, ASP-303.
    "confirm": {
        Language.EN: {
            "title": "Check it went through",
            "detail": (
                f"Sign in to the portal to view the account. If anything looks wrong, "
                f"email {EMAIL} or call the hotline on {HOTLINE}."
            ),
        },
        Language.ES: {
            "title": "Comprueba que se registró",
            "detail": (
                f"Inicia sesión en el portal para ver la cuenta. Si algo no cuadra, "
                f"escribe a {EMAIL} o llama a la línea directa {HOTLINE}."
            ),
        },
        Language.FR: {
            "title": "Vérifier que c'est bien passé",
            "detail": (
                f"Connecte-toi au portail pour consulter le compte. Si quelque chose "
                f"cloche, écris à {EMAIL} ou appelle la ligne directe {HOTLINE}."
            ),
        },
    },
}


# Surfaced prominently on every positive or conditional result. There is no
# deadline in the source (ASP-056, ASP-047, ASP-048), and "have I missed it" is
# the anxiety this answers.
NOTICES: dict[str, dict[Language, str]] = {
    "no_deadline": {
        Language.EN: (
            "There is no deadline. The portal stays open all year, and children are "
            "registered as they reach their fifth birthday."
        ),
        Language.ES: (
            "No hay fecha límite. El portal está abierto todo el año y los niños se "
            "inscriben al cumplir los cinco años."
        ),
        Language.FR: (
            "Il n'y a pas de date limite. Le portail reste ouvert toute l'année et les "
            "enfants sont inscrits dès leur cinquième anniversaire."
        ),
    },
    "free": {
        Language.EN: "Registering is free, and the EC$1,000 comes from the government.",
        Language.ES: "Inscribirse es gratis, y los EC$1.000 los aporta el gobierno.",
        Language.FR: "L'inscription est gratuite, et les 1 000 EC$ viennent du gouvernement.",
    },
}


def contacts(language: Language) -> tuple[str, ...]:
    """The official contact lines, in reading order. Never invented, never varied."""
    labels = {
        Language.EN: ("Email", "Phone", "Hotline"),
        Language.ES: ("Correo", "Teléfono", "Línea directa"),
        Language.FR: ("E-mail", "Téléphone", "Ligne directe"),
    }[language]
    return (
        f"{labels[0]}: {EMAIL}",
        f"{labels[1]}: {PHONES[0]} / {PHONES[1]}",
        f"{labels[2]}: {HOTLINE}",
    )
