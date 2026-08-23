# Voice casting — the full map, and what is missing

**22 August 2026.** Generated from `app/voice/config.py` and `app/voice/registry.py`,
not from memory.

---

## The shape

`validate_registry` requires **every persona × language pair** to resolve, and
raises `VoiceRegistryError` at startup if one does not. That is
`len(Persona) × len(Language)`:

| | Today | After the Kaleb split |
|---|---|---|
| Personas | 5 | **6** |
| Languages | 3 | 3 |
| **Pairs that must resolve** | **15** | **18** |

**The Kaleb split adds three pairs.** `kaleb` understudies `stella`, so it
resolves without new ids — but if anyone ever removes that understudy line,
startup breaks in three places at once.

---

## How a pair resolves — the order

```
1. VOICE_{PERSONA}_{LANG}     per-language id        ← the only one that gives a
                                                       native-sounding voice
2. VOICE_{PERSONA}            the persona's base id  ← one voice for all three
                                                       languages
3. understudy                 another persona's id   ← guest → orion
                                                       kaleb → stella
4. nothing                    VoiceRegistryError at startup
```

> **UPDATE, 22 Aug — step 2 no longer reaches a reader.**
> The client's rule is absolute: an English-trained voice never speaks Spanish
> or French. A pair that resolves only through a base id is now marked
> `native=False`, and both speech endpoints refuse it with the browser fallback
> the player already handles for an outage. Boot is unchanged and text is never
> affected — the reader gets their answer, silently, instead of an English
> accent mangling their language. `registry.uncast_pairs()` lists exactly which
> pairs are silent; today, on a base-ids-only deployment, that is all twelve
> below. There is no override flag: the override is casting the voice.

**Step 2 is where French and Spanish are today.** A base id is a single
ElevenLabs voice used for every language. ElevenLabs will speak French with it,
but it is an English-trained voice: the accent and prosody are wrong, and a
French-speaking child hears it immediately.

---

## The complete variable list

Eighteen per-language ids, six base ids. Nothing else casts a voice.

| Persona | Base | English | Spanish | French |
|---|---|---|---|---|
| Skye | `VOICE_STELLA` | `VOICE_STELLA_EN` | `VOICE_STELLA_ES` | `VOICE_STELLA_FR` |
| Kaleb | `VOICE_KALEB` | `VOICE_KALEB_EN` | `VOICE_KALEB_ES` | `VOICE_KALEB_FR` |
| Zion | `VOICE_ORION` | `VOICE_ORION_EN` | `VOICE_ORION_ES` | `VOICE_ORION_FR` |
| Imani | `VOICE_AURORA` | `VOICE_AURORA_EN` | `VOICE_AURORA_ES` | `VOICE_AURORA_FR` |
| Azuri | `VOICE_NOVA` | `VOICE_NOVA_EN` | `VOICE_NOVA_ES` | `VOICE_NOVA_FR` |
| Guest | `VOICE_GUEST` | `VOICE_GUEST_EN` | `VOICE_GUEST_ES` | `VOICE_GUEST_FR` |

`VOICE_GUEST*` also accepts the legacy `VOICE_EVERYONE*` spelling, kept for one
release.

### Delivery knobs, per persona — optional, tuned by ear

`VOICE_{PERSONA}_STABILITY` · `_SIMILARITY_BOOST` · `_STYLE` · `_SPEED`

These override the table in `registry._DELIVERY`. They exist because tuning a
voice is done by listening, not by editing code. **They are per persona, not per
language** — so a French voice cannot currently be slowed independently of the
English one. If French turns out to need a different pace, that is a small change
to `_TUNABLE`, not a new concept.

---

## What is missing

**I cannot tell you which ids are provisioned in production.** This checkout has
no `.env`, so every variable reads unset here — that is a fact about the sandbox,
not about the deployment. What I can tell you is the shape of the gap:

1. **Twelve per-language ids for ES and FR** — six personas × two languages. Until
   they are set, both languages speak in whatever the base id is, which is an
   English-trained voice.
2. **`VOICE_KALEB`** — and it is more urgent than it looks. Kaleb has no base id,
   so he resolves through the understudy to Stella. In **English** that resolution
   is marked native, which means **it plays**: Kaleb speaks in Skye's voice today,
   at his own pace, in production. The understudy was the right call to stop the
   persona split failing startup, and the argument for leaving it — *"exactly the
   voice this band had yesterday"* — is the same argument that was made for Kaleb
   borrowing Skye's game bank, and the client rejected it. Kaleb and Skye are
   different personas. The game bank has been separated; this has not.

   Unlike the twelve below, setting `VOICE_KALEB` does not turn sound **on**. It
   stops the wrong voice coming out — a failure that looks like nothing is wrong,
   which is why it outlives the ones that look broken.
3. **No per-language delivery tuning** — one pace and one stability per persona,
   shared across all three languages.

### To check the deployment in one command

```bash
for P in STELLA KALEB ORION AURORA NOVA GUEST; do
  for L in EN ES FR; do
    v="VOICE_${P}_${L}"; b="VOICE_${P}"
    printf '%-18s %s\n' "$v" \
      "${!v:+set}${!v:-$( [ -n "${!b}" ] && echo "unset (falls back to $b)" || echo "UNSET AND NO BASE" )}"
  done
done
```

Anything printing **UNSET AND NO BASE** for a pair without an understudy is a
startup failure waiting for the next deploy with `VOICE_ENABLED=true`.

---

## What it costs to fix

**No code change.** The registry already supports per-language ids and has since
it was written.

- Cast twelve voices in ElevenLabs — six for Spanish, six for French — matching
  the delivery brief in `registry._DELIVERY`: Skye slowest and warmest, Kaleb at
  ordinary pace, Zion level, Imani even and trusted, Azuri articulate, Guest
  neutral.
- Set twelve environment variables.
- Restart. `validate_registry` confirms all eighteen pairs at boot.

The listening pass is the real work, and it is the part that has to be done by
someone who speaks the language — a French voice that sounds right to an English
ear is exactly the failure mode this is meant to fix.

---

Prepared by the ASPIRE AI Team for the Government of Saint Kitts and Nevis —
ASPIRE Programme.
