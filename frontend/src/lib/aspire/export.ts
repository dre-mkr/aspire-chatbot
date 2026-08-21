/** Saving a conversation to a file. */

import type { StoredMessage } from "./history";
import { answerToText } from "./knowledge";
import { groupSources } from "./sources";
import type { ChatMessage } from "./use-conversation";

/** A turn this module can write out. */
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

/** The transcript as plain text. */
export function transcriptToText(
	messages: ReadonlyArray<ExportableMessage>,
	savedAt = new Date(),
	/** The language the conversation was held in. */
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
		// A game turn has no prose, so name it rather than silently omit the turn.
		if (message.role === "game") {
			lines.push("ASPIRE AI: [started a learning game]", "");
			continue;
		}
		// Named, not written out, and that is a privacy decision rather than a convenience.
		if (message.role === "eligibility") {
			lines.push("ASPIRE AI: [ran the ASPIRE eligibility check]", "");
			continue;
		}

		// A failed turn is not part of the conversation worth keeping.
		if (message.role !== "assistant") continue;

		lines.push(`ASPIRE AI:  ${answerToText(message.blocks)}`);

		// Grouped the same way the panel groups them, and carrying the URL: a
		// saved transcript whose sources cannot be checked afterwards is a list
		// of assertions. The row ids come too, because they are what a reader
		// quotes when they ring somebody about an answer.
		const groups = groupSources(message.sources);
		if (groups.length > 0) {
			lines.push("", "  Sources");
			for (const group of groups) {
				const name = group.label || group.domain;
				if (name) lines.push(`  · ${name}`);
				if (group.href) lines.push(`    ${group.href}`);
				for (const extract of group.extracts) {
					const said = extract.question || extract.snippet.slice(0, 80);
					if (!said) continue;
					const ref = extract.kbId ? ` [${extract.kbId}]` : "";
					lines.push(`    - ${said}${ref}`);
				}
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
