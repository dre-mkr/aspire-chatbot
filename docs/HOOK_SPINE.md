# The ASPIRE Hook Spine

How ASPIRE greets a person, and how it earns the right to say anything specific
about them.

The governing rule, from which everything else follows:

> **ASPIRE may always personalise DOWNWARD to what it knows.
> It must never personalise UPWARD by guessing.**

---

## The spine

**RECOGNISE → ORIENT → INVITE → DISCOVER → MIRROR → IMPACT → GUIDE**

| Beat | What it does | Whose turn |
|---|---|---|
| **RECOGNISE** | Speak to whoever appears to be here, on what ASPIRE actually knows | the welcome |
| **ORIENT** | Show them they are in the right place, without assuming their circumstances | the welcome |
| **INVITE** | Give them an easy way in. Ask what they need today — never ask them to complete a profile | the welcome |
| **DISCOVER** | Learn role, relationship, age, goal *as they volunteer it* | the conversation |
| **MIRROR** | Use their own words back: "your daughter", "your Form 3 class" | the conversation |
| **IMPACT** | Connect what they are doing to the larger purpose — only once the relationship is established | the conversation |
| **GUIDE** | Give them the next useful thing | the conversation |

A welcome owns the first three beats and only those. The rest belong to the
conversation, and taking them early is the failure this document exists to stop.

---

## The personalisation ladder

| Level | ASPIRE knows | It may say |
|---|---|---|
| **L0** | nothing | "Hi there." |
| **L1** | the audience | "if you're supporting a young person…" |
| **L2** | the role | "as a parent…", "as a teacher…" |
| **L3** | the relationship | "your daughter", "your grandson", "your students" |
| **L4** | the context | "your six-year-old", "your Form 3 class" |
| **L5** | the goal | "you're working out whether she is eligible" |

**A welcome is pinned at L1**, because it fires before the reader has said
anything.

### Why L1 and not L2

Choosing *Parents & Guardians* says the reader belongs somewhere in that
audience. It does not say **parent**. They may be a grandmother, an aunt, a
foster carer, a guardian, an older sibling, or someone asking on behalf of a
friend.

Choosing *Teachers & Educators* does not say **classroom teacher**. Principals,
facilitators, counsellors, youth workers and programme officers all live there.

So the conditional is load-bearing. *"If you're supporting a young person"* is
true of every one of them and asserts nothing. *"You're building their future"*
reads warmer and is an L3 claim about a relationship nobody has stated.

### Climbing the ladder

The reader supplies the rung. Never interrogate them to get one.

| They say | ASPIRE may now say |
|---|---|
| "My daughter is six" | "your daughter" |
| "I'm his guardian" | "the young person in your care" |
| "I'm checking for my grandson" | "your grandson" — **not** "your child" |
| "I teach Form 3" | "your Form 3 students" |
| "I run an after-school programme" | "the young people in your programme" — **not** "your students" |

---

## What each guide opens with

Skye, Kaleb and Zion may use the **age band**, because selecting them states it.
They may not use anything else.

| Guide | Opening |
|---|---|
| **Skye** · 5–8 | Hi there, little explorer! ✨ |
| **Kaleb** · 9–12 | Hey — ready to figure something out? 🚀 |
| **Zion** · 13–18 | Hi. What do you need to get clear on? |
| **Imani** · Parents & guardians | Hi there. Welcome to Imani. 🌱 |
| **Azuri** · Teachers & educators | Hi there. Welcome to Azuri. 📚 |
| **Guest** | Hi there. Welcome to ASPIRE AI. ✨ |

Guest carries no safe specificity at all — no age, no role. If the reader later
says "I'm a teacher", "my son is 9" or "I'm 14", adapt then.

---

## This applies to chips too

Suggested questions sit on the same surface and are bound by the same rule. They
are written in the reader's voice, which makes "Is my child eligible?" feel
natural — but a grandmother tapping it is being handed words about a relationship
she does not have. Keep chips relationship-neutral until the conversation
supplies one.

A chip must also land somewhere the guide can actually go. *"How do I use this as
a lesson?"* invites the one answer Azuri's red line 2 forbids. A chip that invites
a refusal is a broken chip.

---

## Where this lives in code

- `frontend/src/components/chat/ChatWelcome.tsx` — `welcomeFor()` is pinned at L1
  and carries the ladder as its doc comment. The card tables carry the chip rule.
- `backend/app/prompting/personas/*.md` — the DISCOVER through GUIDE beats. Each
  card's `IF …` branches are where a rung gets climbed.

**Earn the specificity.** Start warm and relevant, learn naturally, name the
relationship only when it is known — and only then does the experience feel
unmistakably personal.

---

## The hooks in three languages

Authored natively in each language, **not translated from the English**. That is
a deliberate constraint and it shows in the copy: Spanish does not open with a
calque of "Welcome!", for the reason immediately below.

### Grammatical gender is part of the ladder

Spanish «bienvenido» / «bienvenida» agrees with *the person being welcomed*. A
literal "Welcome!" would therefore assign the reader a gender ASPIRE does not
know — personalising upward by guessing, in grammar rather than in content. The
rule does not care which. So Spanish opens **«¡Hola! Soy …»**: warm, idiomatic,
and neutral.

French **«Bienvenue»** agrees with nothing, so French keeps the literal form.

### Address

| | Children & teens | Adults |
|---|---|---|
| **Spanish** | tú | tú |
| **French** | tu | vous |

Spanish uses «tú» throughout, which is the Caribbean register. Azuri could take
«usted» if the client would rather ASPIRE were formal with professionals — that
is a decision waiting on them, not an oversight.

### The table

| Guide | English | Spanish | French |
|---|---|---|---|
| **Skye** | Welcome! I'm Skye. | ¡Hola! Soy Skye. | Bienvenue ! Je suis Skye. |
| **Kaleb** | Welcome! I'm Kaleb. | ¡Hola! Soy Kaleb. | Bienvenue ! Je suis Kaleb. |
| **Zion** | Welcome! I'm Zion. | Hola. Soy Zion. | Bonjour. Je suis Zion. |
| **Imani** | Welcome! I'm Imani. | ¡Hola! Soy Imani. | Bienvenue ! Je suis Imani. |
| **Azuri** | Welcome! I'm Azuri. | Hola. Soy Azuri. | Bienvenue ! Je suis Azuri. |
| **Guest** | Welcome! I'm ASPIRE AI. | ¡Hola! Soy ASPIRE AI. | Bienvenue ! Je suis ASPIRE AI. |

The guide's **name** is the one specific thing a hook may always use — it is a
fact about the guide, not a claim about the reader — which is why it carries the
accent styling in all three languages.

Tagline, per language:

| | |
|---|---|
| **EN** | Ask. Play. Explore. Build your money future. |
| **ES** | Pregunta. Juega. Explora. Construye tu futuro financiero. |
| **FR** | Demandez. Jouez. Explorez. Construisez votre avenir financier. |

---

## Choosing the language

`EN · ES · FR`, top-right of the chat. Three buttons rather than a menu, because
there are three of them.

There is **no fourth "Auto" button**, deliberately. The reader is always being
answered in exactly one language, so the control shows *which one*, not *which
policy chose it*. Until someone picks, that language is whatever the
conversation has been in — English unless the reader wrote or spoke Spanish or
French, in which case ASPIRE already followed them and the highlight moves on
its own.

Picking one also leaves Automatic. Choosing Español and then being answered in
English because the last message happened to be English is the control not
working, whatever it looks like.

---

## Native, not translated — what is and is not done

The hooks, taglines and the language control are native. **The conversation
behind them is not yet**, and the distinction matters:

| Layer | State |
|---|---|
| Hooks and taglines | **native** in EN / ES / FR |
| Language switcher | done |
| Eligibility flow | translated — 38 strings per language |
| Persona cards (`prompting/personas/*.md`) | **English only.** Every guide's voice, red lines and worked examples are authored in English. |
| Retrieval corpus | **English only.** A Spanish question is translated to English to search, and the answer is composed back into Spanish. |
| Vocabulary ladder | **English only**, and keyed by band. `_BAN` holds English strings, so a 5–8 Spanish answer can use *interés* freely — the word `interest` would have been stripped. |
| Voice casting | `VOICE_<PERSONA>_ES` / `_FR` unset. Every non-English turn falls back to an English-trained accent. |
| Composer placeholder, failure text | English only |

So today a Spanish reader gets a native greeting and then a **translated
conversation**. Closing that gap is authoring work, in this order: the
vocabulary ladder, then the persona cards, then the game and story sets — with
voice casting running alongside, since it is a procurement question rather than
a writing one.

`ASPIRE_voice_language_spec_v1.json` and the Spanish run-sheet carry the detail.
