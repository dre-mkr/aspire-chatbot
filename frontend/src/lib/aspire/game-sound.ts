/**
 * The two sounds the games make, synthesised rather than downloaded.
 *
 * WebAudio instead of an mp3 for three reasons: nothing extra to ship, nothing
 * extra to fetch mid-game, and no licence to keep track of on a government
 * education product. Both sounds are a few oscillators and an envelope.
 *
 * Nothing here ever plays on mount. Every call site is inside a click handler,
 * which is both what browser autoplay policy requires and what makes the sound
 * feel like a response rather than an interruption.
 */

/** Built on first use, because constructing one before a gesture leaves it suspended. */
let context: AudioContext | null = null;

function audio(): AudioContext | null {
	if (typeof window === "undefined") return null;
	try {
		const Ctor =
			window.AudioContext ??
			(window as unknown as { webkitAudioContext?: typeof AudioContext })
				.webkitAudioContext;
		if (!Ctor) return null;
		context ??= new Ctor();
		// Safari suspends until a gesture; every caller is inside one.
		if (context.state === "suspended") void context.resume();
		return context;
	} catch {
		// No audio device, or a policy that forbids it. Silence is a fine outcome.
		return null;
	}
}

/** One short tone. `at` is an offset in seconds so a call can build a phrase. */
function tone(
	ctx: AudioContext,
	{
		freq,
		at,
		length,
		gain = 0.06,
		type = "triangle",
		glideTo,
	}: {
		freq: number;
		at: number;
		length: number;
		gain?: number;
		type?: OscillatorType;
		glideTo?: number;
	},
) {
	const start = ctx.currentTime + at;
	const osc = ctx.createOscillator();
	const amp = ctx.createGain();

	osc.type = type;
	osc.frequency.setValueAtTime(freq, start);
	if (glideTo !== undefined) {
		osc.frequency.exponentialRampToValueAtTime(glideTo, start + length);
	}

	// A quick rise and a slow fall. A square-edged envelope clicks.
	amp.gain.setValueAtTime(0.0001, start);
	amp.gain.exponentialRampToValueAtTime(gain, start + 0.012);
	amp.gain.exponentialRampToValueAtTime(0.0001, start + length);

	osc.connect(amp).connect(ctx.destination);
	osc.start(start);
	osc.stop(start + length + 0.02);
}

/**
 * A coin landing in the bank. Two bright notes a fifth apart, rising.
 *
 * Deliberately quiet and deliberately short: this fires on every right answer,
 * and anything longer than a blink becomes something to sit through.
 */
export function playCoin(enabled: boolean) {
	if (!enabled) return;
	const ctx = audio();
	if (!ctx) return;
	tone(ctx, { freq: 988, at: 0, length: 0.09, gain: 0.05 });
	tone(ctx, { freq: 1319, at: 0.055, length: 0.13, gain: 0.045 });
}

/**
 * A coin rolling back out. One note, falling.
 *
 * Not a buzzer. A wrong answer in a learning game is a thing to be told about,
 * not punished for, and the sound is the one place that attitude is easiest to
 * get wrong.
 */
export function playMiss(enabled: boolean) {
	if (!enabled) return;
	const ctx = audio();
	if (!ctx) return;
	tone(ctx, {
		freq: 440,
		glideTo: 294,
		at: 0,
		length: 0.2,
		gain: 0.04,
		type: "sine",
	});
}
