/**
 * Saving a conversation to a file.
 *
 * Everything this needs is already on the client — the transcript itself, and
 * `answerToText` for flattening an answer back to prose — so saving never goes
 * near the service and works with the backend down.
 */

import type { StoredMessage } from "./history";
import { answerToText } from "./knowledge";
import type { ChatMessage } from "./use-conversation";

/**
 * A turn this module can write out.
 *
 * Both the live `ChatMessage` and the stored `StoredMessage` satisfy it: the
 * transcript only ever reads `role`, `text`, `blocks` and `sources`, never the
 * id. That is what lets the rail save any conversation on the device, not just
 * the one currently open.
 */
export type ExportableMessage = ChatMessage | StoredMessage;

/** `2026-07-31-1408` — sorts by date and is legal on every filesystem. */
function fileStamp(date: Date) {
	const pad = (value: number) => String(value).padStart(2, "0");
	return [
		date.getFullYear(),
		pad(date.getMonth() + 1),
		pad(date.getDate()),
		`${pad(date.getHours())}${pad(date.getMinutes())}`,
	].join("-");
}

/**
 * The transcript as plain text.
 *
 * Plain text rather than markdown or PDF: it opens on any phone, pastes into
 * any homework, and prints. Sources come with each answer because an answer
 * without its evidence is the part worth checking.
 */
export function transcriptToText(
	messages: ReadonlyArray<ExportableMessage>,
	savedAt = new Date(),
	/**
	 * The language the conversation was held in.
	 *
	 * `toLocaleString()` with no argument follows the *browser's* locale, which
	 * is a different question from the one this product asks. A conversation
	 * held in French, saved on a device set to English, was stamped with an
	 * English date — the file disagreed with its own contents.
	 *
	 * `undefined` means "no opinion", which is the old behaviour and correct for
	 * a caller that genuinely does not know.
	 */
	language?: string,
) {
	const lines = [
		"ASPIRE AI — saved conversation",
		savedAt.toLocaleString(language),
		"",
	];

	for (const message of messages) {
		if (message.role === "user") {
			lines.push(`You:  ${message.text}`, "");
			continue;
		}
		// A game turn has no prose to write out, so it is named rather than
		// skipped -- a transcript that silently omits it reads as if nobody
		// answered.
		if (message.role === "game") {
			lines.push("ASPIRE AI: [started a learning game]", "");
			continue;
		}
		// Named, not written out, and that is a privacy decision rather than a
		// convenience. A saved transcript gets emailed and forwarded; the check's
		// answers and its verdict stay in this browser, so what leaves is the
		// fact that it happened and nothing about the person who ran it.
		if (message.role === "eligibility") {
			lines.push("ASPIRE AI: [ran the ASPIRE eligibility check]", "");
			continue;
		}

		// A failed turn is not part of the conversation worth keeping.
		if (message.role !== "assistant") continue;

		lines.push(`ASPIRE AI:  ${answerToText(message.blocks)}`);

		if (message.sources.length > 0) {
			lines.push("", "  Sources");
			for (const source of message.sources) {
				const label = source.metadata?.question ?? source.metadata?.category;
				lines.push(`  · ${String(label ?? source.content.slice(0, 80))}`);
			}
		}
		lines.push("");
	}

	lines.push(
		"—",
		"ASPIRE AI can make mistakes. Check important info with your mentor.",
	);
	return lines.join("\n");
}

/**
 * An amount of money, in the currency this programme actually uses.
 *
 * There is no `Intl.NumberFormat` anywhere in the client today, and no UI
 * renders an amount — every figure a reader sees is literal text inside a
 * knowledge-base answer. This exists so that stops being true safely: the first
 * component to render an amount should reach for this rather than invent its
 * own, because that is the moment a French conversation starts showing
 * `$1,234.50` instead of `1 234,50 $EC`.
 *
 * XCD is the East Caribbean dollar, the currency of St. Kitts and Nevis.
 */
export function formatXCD(amount: number, language = "en") {
	return new Intl.NumberFormat(language, {
		style: "currency",
		currency: "XCD",
	}).format(amount);
}

/** A date, in the language the conversation is being held in. */
export function formatDate(date: Date, language = "en") {
	return new Intl.DateTimeFormat(language, {
		dateStyle: "long",
	}).format(date);
}

/** Writes the transcript out as a download. No-op with nothing to save. */
export function downloadTranscript(
	messages: ReadonlyArray<ExportableMessage>,
	language?: string,
) {
	if (messages.length === 0) return;

	const blob = new Blob([transcriptToText(messages, new Date(), language)], {
		type: "text/plain;charset=utf-8",
	});
	const url = URL.createObjectURL(blob);
	const link = document.createElement("a");
	link.href = url;
	link.download = `aspire-chat-${fileStamp(new Date())}.txt`;
	document.body.append(link);
	link.click();
	link.remove();
	// Revoking straight away can race the browser's own read of the blob.
	setTimeout(() => URL.revokeObjectURL(url), 10_000);
}
