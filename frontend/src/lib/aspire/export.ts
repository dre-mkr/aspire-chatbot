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
) {
	const lines = [
		"ASPIRE AI — saved conversation",
		savedAt.toLocaleString(),
		"",
	];

	for (const message of messages) {
		if (message.role === "user") {
			lines.push(`You:  ${message.text}`, "");
			continue;
		}
		// A failed turn is not part of the conversation worth keeping.
		if (message.role !== "assistant") continue;

		lines.push(`ASPIRE AI:  ${answerToText(message.blocks)}`);

		if (message.sources.length > 0) {
			lines.push("", "  Sources");
			for (const source of message.sources) {
				const label = source.metadata.question ?? source.metadata.category;
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

/** Writes the transcript out as a download. No-op with nothing to save. */
export function downloadTranscript(
	messages: ReadonlyArray<ExportableMessage>,
) {
	if (messages.length === 0) return;

	const blob = new Blob([transcriptToText(messages)], {
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
