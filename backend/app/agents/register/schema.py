"""The application form, as Pydantic."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: St Kitts and Nevis parishes.
PARISHES: tuple[str, ...] = (
    "Christ Church Nichola Town",
    "Saint Anne Sandy Point",
    "Saint George Basseterre",
    "Saint George Gingerland",
    "Saint James Windward",
    "Saint John Capisterre",
    "Saint John Figtree",
    "Saint Mary Cayon",
    "Saint Paul Capisterre",
    "Saint Paul Charlestown",
    "Saint Peter Basseterre",
    "Saint Thomas Lowland",
    "Saint Thomas Middle Island",
    "Trinity Palmetto Point",
)

RELATIONSHIPS: tuple[str, ...] = (
    "mother",
    "father",
    "grandmother",
    "grandfather",
    "aunt",
    "uncle",
    "legal guardian",
    "other",
)


class DocumentRef(BaseModel):
    """A document that lives in object storage."""

    model_config = ConfigDict(extra="forbid")

    document_id: str
    mime: str = ""
    size_bytes: int = 0
    #: Never `clean` by default.
    scan_status: Literal["pending", "clean", "infected", "failed"] = "pending"
    #: `doc_check`'s advisory verdict. Never blocks anything -- see E3.
    check_confidence: float = 0.0
    check_notes: str = ""


class GuardianSection(BaseModel):
    """The adult opening the account. Completes fully before any child."""

    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=2, max_length=120)
    national_id: str = Field(min_length=5, max_length=32)
    date_of_birth: date
    relationship: str
    phone: str = Field(min_length=7, max_length=24)
    email: str | None = Field(default=None, max_length=160)
    address_line1: str = Field(min_length=4, max_length=160)
    parish: str
    id_document: DocumentRef | None = None
    proof_of_address: DocumentRef | None = None

    @field_validator("parish")
    @classmethod
    def _known_parish(cls, value: str) -> str:
        if value not in PARISHES:
            raise ValueError(f"{value!r} is not a parish")
        return value

    @field_validator("relationship")
    @classmethod
    def _known_relationship(cls, value: str) -> str:
        if value.lower() not in RELATIONSHIPS:
            raise ValueError(f"{value!r} is not a relationship we record")
        return value.lower()

    @field_validator("date_of_birth")
    @classmethod
    def _guardian_is_an_adult(cls, value: date) -> date:
        """Eighteen or over."""
        today = date.today()
        age = today.year - value.year - ((today.month, today.day) < (value.month, value.day))
        if age < 18:
            raise ValueError("a guardian must be 18 or over")
        if age > 120:
            raise ValueError("that date of birth is not plausible")
        return value


class ChildSection(BaseModel):
    """One child. The form loops this per additional child."""

    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=2, max_length=120)
    date_of_birth: date
    sex: Literal["female", "male", "other"]
    school: str | None = Field(default=None, max_length=160)
    birth_certificate: DocumentRef | None = None
    photo: DocumentRef | None = None
    existing_account: bool = False

    @field_validator("date_of_birth")
    @classmethod
    def _in_the_programmes_range(cls, value: date) -> date:
        today = date.today()
        age = today.year - value.year - ((today.month, today.day) < (value.month, value.day))
        if age < 0:
            raise ValueError("that date is in the future")
        if age > 18:
            raise ValueError("ASPIRE is for children up to 18")
        return value


class Application(BaseModel):
    model_config = ConfigDict(extra="forbid")

    guardian: GuardianSection | None = None
    children: list[ChildSection] = Field(default_factory=list)
    #: The consent text VERSION agreed to, not the text.
    consent_version: str | None = None
    attested_at: datetime | None = None
    attested_ip: str | None = None


# ── slots: the conversational walk over the schema ──────────────────────────


@dataclass(frozen=True, slots=True)
class Slot:
    """One question, and everything the conversation needs around it."""

    #: Dotted path: "guardian.national_id", "child.birth_certificate".
    path: str
    #: What a reviewer and a review card call it.
    label: str
    #: How to ask, per locale.
    prompt: dict[str, str]
    #: What to say when the answer did not parse.
    reask: dict[str, str]
    #: Parses and validates. Returns `(value, None)` or `(None, reason)`.
    parse: Callable[[str], tuple[Any, str | None]]
    #: Encrypted in `application_pii`, and `[collected: ...]` in the transcript.
    sensitive: bool = False
    #: Collected through the upload interrupt rather than by typing.
    document: bool = False
    #: An optional slot may be skipped with "skip" or an empty answer.
    optional: bool = False
    #: Tap targets, when the answer is one of a closed set.
    options: tuple[str, ...] = ()


# ── parsers ──────────────────────────────────────────────────────────────────


def _text(minimum: int = 2, maximum: int = 160):
    def parse(raw: str) -> tuple[Any, str | None]:
        value = " ".join(raw.split())
        if len(value) < minimum:
            return None, "too short"
        if len(value) > maximum:
            return None, "too long"
        return value, None

    return parse


#: Day-first, because that is how the date is written and said here.
_DATE_PATTERNS = ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d")


def _parse_date(raw: str) -> tuple[Any, str | None]:
    text = raw.strip()
    for pattern in _DATE_PATTERNS:
        try:
            return datetime.strptime(text, pattern).date(), None
        except ValueError:
            continue
    return None, "not a date we could read"


_PHONE = re.compile(r"^\+?[\d\s().-]{7,24}$")


def _parse_phone(raw: str) -> tuple[Any, str | None]:
    text = raw.strip()
    if not _PHONE.match(text):
        return None, "not a phone number"
    digits = re.sub(r"\D", "", text)
    if len(digits) < 7:
        return None, "too few digits"
    return text, None


_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


def _parse_email(raw: str) -> tuple[Any, str | None]:
    text = raw.strip()
    if not text or text.lower() in ("skip", "none", "no"):
        return None, None
    if not _EMAIL.match(text):
        return None, "not an email address"
    return text, None


_NATIONAL_ID = re.compile(r"^[A-Za-z]{0,3}[\s-]?\d{5,14}$")


def _parse_national_id(raw: str) -> tuple[Any, str | None]:
    text = " ".join(raw.split()).upper()
    if not _NATIONAL_ID.match(text):
        return None, "not an ID number"
    return text, None


def _fold(text: str) -> str:
    """One spelling, out of the many people actually use."""
    text = text.lower().replace("'", "").replace("’", "")
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    return re.sub(r"\b(st|ste|snt)\b", "saint", text)


def _tokens_fit(answer: str, option: str) -> bool:
    """Whether every word typed corresponds to a word in the option."""
    words = option.split()
    return all(
        any(
            token == word
            or (len(token) >= 3 and word.startswith(token))
            or (len(word) >= 3 and token.startswith(word))
            for word in words
        )
        for token in answer.split()
    )


def _one_of(options: tuple[str, ...]):
    def parse(raw: str) -> tuple[Any, str | None]:
        text = raw.strip().lower()
        for option in options:
            if text == option.lower():
                return option, None

        # Everything below is the loose path, because a parent types "Cayon" for "Saint Mary Cayon" -- or "St.
        answer = _fold(raw)
        if not answer:
            return None, "not one of the options"

        folded = {option: _fold(option) for option in options}
        for option, name in folded.items():
            if answer == name:
                return option, None

        matches = [
            option
            for option, name in folded.items()
            # `name in answer` catches the other direction: the official list writes two of the Nevis parishes with a "(Nev…
            if answer in name or name in answer or _tokens_fit(answer, name)
        ]
        if len(matches) == 1:
            return matches[0], None
        if len(matches) > 1:
            # "Basseterre" is two parishes and "Saint George" is two more.
            return None, f"matches more than one of: {', '.join(matches)}"
        return None, "not one of the options"

    return parse


def _parse_yes_no(raw: str) -> tuple[Any, str | None]:
    text = raw.strip().lower()
    if text in ("yes", "y", "yeah", "yep", "si", "sí", "oui"):
        return True, None
    if text in ("no", "n", "nope", "non"):
        return False, None
    return None, "not a yes or a no"


def _parse_document(raw: str) -> tuple[Any, str | None]:
    """A document slot never parses typed text."""
    return None, "this one needs a photo, not typing"


# ── the walk ─────────────────────────────────────────────────────────────────

GUARDIAN_SLOTS: tuple[Slot, ...] = (
    Slot(
        path="guardian.full_name",
        label="Your full name",
        prompt={
            "en": "Let's start with you. What is your full name?",
            "es": "Empecemos contigo. ¿Cuál es tu nombre completo?",
            "fr": "Commençons par toi. Quel est ton nom complet ?",
        },
        reask={
            "en": "I need your full name as it appears on your ID — first and last.",
            "es": "Necesito tu nombre completo como aparece en tu documento.",
            "fr": "Il me faut ton nom complet tel qu'il figure sur ta pièce d'identité.",
        },
        parse=_text(),
        sensitive=True,
    ),
    Slot(
        path="guardian.national_id",
        label="Your national ID number",
        prompt={
            "en": "What is your national ID number?",
            "es": "¿Cuál es tu número de identificación nacional?",
            "fr": "Quel est ton numéro d'identité nationale ?",
        },
        reask={
            "en": "That does not look like an ID number. It is usually letters then digits — like A1234567.",
            "es": "Eso no parece un número de identificación. Suele ser letras y dígitos, como A1234567.",
            "fr": "Cela ne ressemble pas à un numéro d'identité. C'est souvent des lettres puis des chiffres, comme A1234567.",
        },
        parse=_parse_national_id,
        sensitive=True,
    ),
    Slot(
        path="guardian.date_of_birth",
        label="Your date of birth",
        prompt={
            "en": "What is your date of birth?",
            "es": "¿Cuál es tu fecha de nacimiento?",
            "fr": "Quelle est ta date de naissance ?",
        },
        reask={
            "en": "I need the date as day/month/year — like 14/03/1985.",
            "es": "Necesito la fecha como día/mes/año — por ejemplo 14/03/1985.",
            "fr": "Il me faut la date en jour/mois/année — par exemple 14/03/1985.",
        },
        parse=_parse_date,
        sensitive=True,
    ),
    Slot(
        path="guardian.relationship",
        label="Your relationship to the child",
        prompt={
            "en": "And how are you related to the child?",
            "es": "¿Y cuál es tu relación con el niño o la niña?",
            "fr": "Et quel est ton lien avec l'enfant ?",
        },
        reask={
            "en": "Pick the closest one — mother, father, grandmother, grandfather, aunt, uncle, legal guardian, or other.",
            "es": "Elige la más cercana — madre, padre, abuela, abuelo, tía, tío, tutor legal u otra.",
            "fr": "Choisis la plus proche — mère, père, grand-mère, grand-père, tante, oncle, tuteur légal ou autre.",
        },
        parse=_one_of(RELATIONSHIPS),
        options=RELATIONSHIPS,
    ),
    Slot(
        path="guardian.phone",
        label="Your phone number",
        prompt={
            "en": "What number can ASPIRE reach you on?",
            "es": "¿A qué número puede llamarte ASPIRE?",
            "fr": "À quel numéro ASPIRE peut-il te joindre ?",
        },
        reask={
            "en": "I need a phone number with the digits — like 869 555 0123.",
            "es": "Necesito un número de teléfono con los dígitos — por ejemplo 869 555 0123.",
            "fr": "Il me faut un numéro de téléphone avec les chiffres — par exemple 869 555 0123.",
        },
        parse=_parse_phone,
        sensitive=True,
    ),
    Slot(
        path="guardian.email",
        label="Your email address",
        prompt={
            "en": "An email address, if you have one? You can skip this.",
            "es": "¿Un correo electrónico, si tienes? Puedes saltarlo.",
            "fr": "Une adresse e-mail, si tu en as une ? Tu peux passer.",
        },
        reask={
            "en": "That does not look like an email — it needs an @ in it. Or say skip.",
            "es": "Eso no parece un correo — necesita una @. O di saltar.",
            "fr": "Cela ne ressemble pas à un e-mail — il faut un @. Ou dis passer.",
        },
        parse=_parse_email,
        sensitive=True,
        optional=True,
    ),
    Slot(
        path="guardian.address_line1",
        label="Your address",
        prompt={
            "en": "What is your street address?",
            "es": "¿Cuál es tu dirección?",
            "fr": "Quelle est ton adresse ?",
        },
        reask={
            "en": "I need the street and number — like 12 Cayon Street.",
            "es": "Necesito la calle y el número — por ejemplo 12 Cayon Street.",
            "fr": "Il me faut la rue et le numéro — par exemple 12 Cayon Street.",
        },
        parse=_text(minimum=4),
        sensitive=True,
    ),
    Slot(
        path="guardian.parish",
        label="Your parish",
        prompt={
            "en": "And which parish?",
            "es": "¿Y en qué parroquia?",
            "fr": "Et quelle paroisse ?",
        },
        reask={
            # Not "tap one of the options": there are fourteen parishes and the chips only ever show four, so for ten of th…
            "en": "I need the full parish name — like Saint Mary Cayon. You can type it, or tap one of the options.",
            "es": "Necesito el nombre completo de la parroquia — por ejemplo Saint Mary Cayon. Puedes escribirlo o tocar una de las opciones.",
            "fr": "Il me faut le nom complet de la paroisse — par exemple Saint Mary Cayon. Tu peux l'écrire ou toucher une des options.",
        },
        parse=_one_of(PARISHES),
        options=PARISHES,
    ),
    Slot(
        path="guardian.id_document",
        label="A photo of your ID",
        prompt={
            "en": "Now a photo of your ID.",
            "es": "Ahora una foto de tu documento de identidad.",
            "fr": "Maintenant une photo de ta pièce d'identité.",
        },
        reask={
            "en": "I could not read that one. A clear photo of the whole card is fine.",
            "es": "No pude leer esa. Una foto clara de toda la tarjeta está bien.",
            "fr": "Je n'ai pas pu lire celle-ci. Une photo claire de toute la carte suffit.",
        },
        parse=_parse_document,
        document=True,
    ),
    Slot(
        path="guardian.proof_of_address",
        label="Proof of your address",
        prompt={
            "en": "And something showing your address — a bill works.",
            "es": "Y algo que muestre tu dirección — una factura sirve.",
            "fr": "Et quelque chose qui montre ton adresse — une facture convient.",
        },
        reask={
            "en": "I could not read that one. A photo of the whole page is fine.",
            "es": "No pude leer esa. Una foto de toda la página está bien.",
            "fr": "Je n'ai pas pu lire celle-ci. Une photo de toute la page suffit.",
        },
        parse=_parse_document,
        document=True,
    ),
)

CHILD_SLOTS: tuple[Slot, ...] = (
    Slot(
        path="child.full_name",
        label="The child's full name",
        prompt={
            "en": "Now the child. What is their full name?",
            "es": "Ahora el niño o la niña. ¿Cuál es su nombre completo?",
            "fr": "Maintenant l'enfant. Quel est son nom complet ?",
        },
        reask={
            "en": "I need their full name as it appears on the birth certificate.",
            "es": "Necesito su nombre completo como aparece en el certificado de nacimiento.",
            "fr": "Il me faut son nom complet tel qu'il figure sur l'acte de naissance.",
        },
        parse=_text(),
        sensitive=True,
    ),
    Slot(
        path="child.date_of_birth",
        label="The child's date of birth",
        prompt={
            "en": "And their date of birth?",
            "es": "¿Y su fecha de nacimiento?",
            "fr": "Et sa date de naissance ?",
        },
        reask={
            "en": "I need the date as day/month/year — like 14/03/2015.",
            "es": "Necesito la fecha como día/mes/año — por ejemplo 14/03/2015.",
            "fr": "Il me faut la date en jour/mois/année — par exemple 14/03/2015.",
        },
        parse=_parse_date,
        sensitive=True,
    ),
    Slot(
        path="child.sex",
        label="The child's sex",
        prompt={
            "en": "Female, male, or other?",
            "es": "¿Femenino, masculino u otro?",
            "fr": "Féminin, masculin ou autre ?",
        },
        reask={
            "en": "Tap one of the three.",
            "es": "Toca una de las tres.",
            "fr": "Touche l'une des trois.",
        },
        parse=_one_of(("female", "male", "other")),
        options=("female", "male", "other"),
    ),
    Slot(
        path="child.school",
        label="The child's school",
        prompt={
            "en": "Which school do they go to? You can skip this.",
            "es": "¿A qué escuela va? Puedes saltarlo.",
            "fr": "À quelle école va-t-il ou elle ? Tu peux passer.",
        },
        reask={
            "en": "Just the school's name, or say skip.",
            "es": "Solo el nombre de la escuela, o di saltar.",
            "fr": "Juste le nom de l'école, ou dis passer.",
        },
        parse=_text(minimum=2),
        optional=True,
    ),
    Slot(
        path="child.existing_account",
        label="Already has an ASPIRE account",
        prompt={
            "en": "Do they already have an ASPIRE account?",
            "es": "¿Ya tiene una cuenta ASPIRE?",
            "fr": "A-t-il ou elle déjà un compte ASPIRE ?",
        },
        reask={
            "en": "Just yes or no.",
            "es": "Solo sí o no.",
            "fr": "Juste oui ou non.",
        },
        parse=_parse_yes_no,
        options=("yes", "no"),
    ),
    Slot(
        path="child.birth_certificate",
        label="The child's birth certificate",
        prompt={
            "en": "A photo of their birth certificate.",
            "es": "Una foto de su certificado de nacimiento.",
            "fr": "Une photo de son acte de naissance.",
        },
        reask={
            "en": "I could not read that one. A clear photo of the whole page is fine.",
            "es": "No pude leer esa. Una foto clara de toda la página está bien.",
            "fr": "Je n'ai pas pu lire celle-ci. Une photo claire de toute la page suffit.",
        },
        parse=_parse_document,
        document=True,
    ),
    Slot(
        path="child.photo",
        label="A photo of the child",
        prompt={
            "en": "And a recent photo of them, for the passbook. You can skip this.",
            "es": "Y una foto reciente, para la libreta. Puedes saltarlo.",
            "fr": "Et une photo récente, pour le carnet. Tu peux passer.",
        },
        reask={
            "en": "A clear photo of their face. Or say skip.",
            "es": "Una foto clara de su cara. O di saltar.",
            "fr": "Une photo claire de son visage. Ou dis passer.",
        },
        parse=_parse_document,
        document=True,
        optional=True,
    ),
)

#: The whole walk.
SLOTS: tuple[Slot, ...] = GUARDIAN_SLOTS + CHILD_SLOTS

BY_PATH: dict[str, Slot] = {slot.path: slot for slot in SLOTS}


def slot_for(path: str) -> Slot | None:
    return BY_PATH.get(path)


def sensitive_paths() -> frozenset[str]:
    """Every slot whose value is encrypted and never reaches the transcript."""
    return frozenset(slot.path for slot in SLOTS if slot.sensitive)


def next_missing(
    filled: dict[str, Any],
    *,
    child_index: int = 0,
    allow_sensitive: bool = True,
    barred: frozenset[str] | set[str] | None = None,
) -> Slot | None:
    """The next slot to ask for, in order."""
    withheld = set(barred or ())

    for slot in GUARDIAN_SLOTS:
        if allow_sensitive is False and slot.sensitive:
            continue
        if slot.path in withheld:
            continue
        if filled.get(slot.path) in (None, ""):
            return slot

    for slot in CHILD_SLOTS:
        if allow_sensitive is False and slot.sensitive:
            continue
        key = child_key(slot.path, child_index)
        if slot.path in withheld or key in withheld:
            continue
        if filled.get(key) in (None, ""):
            return slot

    return None


def child_key(path: str, index: int) -> str:
    """`child.full_name` for child 2 is `child.1.full_name`."""
    if not path.startswith("child."):
        return path
    return f"child.{index}.{path[len('child.'):]}"


def display_value(slot: Slot, value: Any) -> str:
    """What a review card shows."""
    if value in (None, ""):
        return ""
    if isinstance(value, date):
        text = value.strftime("%d/%m/%Y")
    elif isinstance(value, bool):
        text = "Yes" if value else "No"
    elif isinstance(value, dict):
        return "Uploaded"
    else:
        text = str(value)

    if not slot.sensitive:
        return text
    if "@" in text:
        name, _, domain = text.partition("@")
        return f"{name[:2]}{'•' * max(1, len(name) - 2)}@{domain}"
    if len(text) <= 4:
        return "•" * len(text)
    return f"{'•' * (len(text) - 4)}{text[-4:]}"
