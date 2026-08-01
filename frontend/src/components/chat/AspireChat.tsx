import { useCallback, useEffect, useRef, useState } from "react";
import { downloadTranscript } from "#/lib/aspire/export";
import {
	fetchGameState,
	type GamePersona,
	type GameState,
} from "#/lib/aspire/games";
import type { StoredConversation } from "#/lib/aspire/history";
import { answerToText, starterPrompts } from "#/lib/aspire/knowledge";
import { useConversation } from "#/lib/aspire/use-conversation";
import { useVoice } from "#/lib/aspire/use-voice";
import { useMediaQuery } from "#/lib/use-media-query";
import { Composer } from "./Composer";
import { Rail } from "./Rail";
import { TopBar } from "./TopBar";
import { Transcript } from "./Transcript";
import { VoiceConsent, VoiceNote } from "./Voice";

/** Below this the rail stops being a column and becomes a modal drawer. */
const COMPACT = "(max-width: 860px)";
/** How far from the bottom still counts as "following along". */
const STICK_THRESHOLD_PX = 160;

interface AspireChatProps {
	/**
	 * Which ASPIRE audience this is: "stella", "orion", "aurora" or "nova".
	 *
	 * Nothing selects one yet, so it defaults to unknown — which the service
	 * treats as permissive rather than as any particular persona. Wire a picker
	 * to this prop and the games gate, the voice, and the card's whole scale
	 * follow with no further change.
	 */
	persona?: GamePersona | null;
}

export function AspireChat({ persona = null }: AspireChatProps = {}) {
	// Read-aloud has to start the moment an answer lands, but the voice layer
	// needs the thread id the conversation owns. The ref breaks that cycle: the
	// conversation calls through it, and the effect below keeps it current.
	const speakArrival = useRef<(id: number, text: string) => void>(() => {});

	const {
		phase,
		messages,
		streaming,
		isThinking,
		followUps,
		history,
		threadId,
		send,
		regenerate,
		stop,
		openPast,
		reset,
	} = useConversation({
		onAnswer: (id, text) => speakArrival.current(id, text),
		persona,
	});

	const compact = useMediaQuery(COMPACT);
	const [railCollapsed, setRailCollapsed] = useState(false);
	const [drawerOpen, setDrawerOpen] = useState(false);
	const [simpleMode, setSimpleMode] = useState(false);
	// Lifted so a transcript can land here for the user to check before sending.
	const [draft, setDraft] = useState("");

	const voice = useVoice({ onTranscript: setDraft, threadId });

	// Only new answers are spoken. Reopening a past conversation restores its
	// messages without going through onAnswer, so nothing replays on load.
	useEffect(() => {
		speakArrival.current = (id, text) => {
			if (voice.autoSpeak && voice.available) void voice.play(id, text);
		};
	}, [voice.autoSpeak, voice.available, voice.play]);

	const threadRef = useRef<HTMLDivElement>(null);

	// The game lives on the server, keyed by this thread. The browser holds none
	// of it, which is what makes a refresh mid-word a non-event — and it is also
	// how the card learns the assistant started a game through its own tools,
	// without the chat response needing a field for it.
	const [game, setGame] = useState<GameState | null>(null);
	const settled = !isThinking && !streaming;

	// biome-ignore lint/correctness/useExhaustiveDependencies: refetch trigger
	useEffect(() => {
		if (!threadId || !settled) return;
		let live = true;
		void fetchGameState(threadId)
			.then((state) => {
				// Only ever adopt a game from the server; never clear one here. A
				// finished game has no session left, but its card is still showing
				// the child what they just learned, and it closes on their say-so.
				if (live && state) setGame(state);
			})
			// Games are additive. If the endpoint is off or unreachable, the card
			// simply does not appear and the conversation is unaffected.
			.catch(() => undefined);
		return () => {
			live = false;
		};
	}, [threadId, messages.length, settled]);

	const railClosed = compact ? !drawerOpen : railCollapsed;
	const drawerModal = compact && drawerOpen && phase === "chat";

	// Announce discrete events, not the stream. A live region around the
	// transcript itself would read every four-word tick out loud.
	const latest = messages.at(-1);
	const announcement =
		isThinking || streaming
			? "ASPIRE AI is writing a reply."
			: latest?.role === "error"
				? latest.text
				: latest?.role === "assistant"
					? answerToText(latest.blocks)
					: "";

	// Follow the answer as it streams, but only while the reader is already at
	// the bottom — scrolling up to re-read something should not get yanked back.
	// `streaming` is the trigger rather than an input: every revealed word grows
	// the thread and has to be chased. Dropping it freezes the scroll mid-answer.
	// biome-ignore lint/correctness/useExhaustiveDependencies: change trigger
	useEffect(() => {
		const thread = threadRef.current;
		if (!thread || phase !== "chat") return;

		const distance =
			thread.scrollHeight - thread.scrollTop - thread.clientHeight;
		if (distance < STICK_THRESHOLD_PX) {
			thread.scrollTop = thread.scrollHeight;
		}
	}, [messages, streaming, isThinking, phase]);

	// Captured when the drawer is opened, not when the effect runs: by then the
	// workspace is already inert and the browser has blurred the button, so
	// `activeElement` would be the body and focus would have nowhere to go back to.
	const railTrigger = useRef<HTMLElement | null>(null);

	const openDrawer = useCallback(() => {
		railTrigger.current = document.activeElement as HTMLElement | null;
		setDrawerOpen(true);
	}, []);

	// A drawer that leaves the page behind it reachable is not a drawer: Tab
	// walks straight out of it and into the composer under the scrim. For as
	// long as it is open the workspace goes inert, focus moves into the drawer,
	// and whatever opened it gets focus back on close.
	useEffect(() => {
		if (!drawerModal) return;

		document
			.getElementById("aspire-rail")
			?.querySelector<HTMLElement>("button")
			?.focus();

		const close = (event: KeyboardEvent) => {
			if (event.key === "Escape") setDrawerOpen(false);
		};
		window.addEventListener("keydown", close);
		return () => {
			window.removeEventListener("keydown", close);
			const trigger = railTrigger.current;
			railTrigger.current = null;
			if (trigger?.isConnected) trigger.focus();
		};
	}, [drawerModal]);

	const toggleRail = useCallback(() => {
		if (compact) setDrawerOpen((open) => !open);
		else setRailCollapsed((collapsed) => !collapsed);
	}, [compact]);

	// Asking something new, reopening a conversation, or starting a fresh one all
	// make whatever is being read aloud irrelevant, so audio stops with them.
	const { stopPlayback } = voice;

	// simpleMode is read at send time rather than captured per conversation, so
	// toggling it changes the next answer without disturbing the ones already up.
	const ask = useCallback(
		(question: string) => {
			stopPlayback();
			send(question, simpleMode);
		},
		[send, simpleMode, stopPlayback],
	);

	// Carries the id of the answer being retried, so it replaces that one
	// rather than whatever happens to be last in the transcript.
	const handleRegenerate = useCallback(
		(messageId: number) => {
			stopPlayback();
			regenerate(messageId, simpleMode);
		},
		[regenerate, simpleMode, stopPlayback],
	);

	const handleStop = useCallback(() => {
		stopPlayback();
		stop();
	}, [stop, stopPlayback]);

	// Reopening or starting a conversation moves to a different thread, and a
	// game belongs to the thread it was played in. Clear it locally; the effect
	// above refetches whatever the new thread actually has.
	const handleOpenPast = useCallback(
		(conversation: StoredConversation) => {
			stopPlayback();
			setDrawerOpen(false);
			setGame(null);
			openPast(conversation);
		},
		[openPast, stopPlayback],
	);

	const handleNewChat = useCallback(() => {
		stopPlayback();
		setDrawerOpen(false);
		setGame(null);
		reset();
	}, [reset, stopPlayback]);

	const handleSaveChat = useCallback(
		() => downloadTranscript(messages),
		[messages],
	);
	// Nothing to save until an answer has actually landed.
	const canSave = messages.some((message) => message.role === "assistant");

	return (
		<div
			className="app"
			data-phase={phase}
			data-rail={railClosed ? "collapsed" : "expanded"}
		>
			<div className="atmosphere" aria-hidden="true">
				<span />
				<span />
				<span />
				<span />
			</div>

			<div className="frame">
				<Rail
					collapsed={railClosed}
					unreachable={phase === "landing" || (compact && railClosed)}
					history={history}
					activeThreadId={threadId}
					onToggle={toggleRail}
					onNewChat={handleNewChat}
					onOpenPast={handleOpenPast}
				/>

				{drawerModal ? (
					<button
						type="button"
						className="rail-scrim"
						onClick={() => setDrawerOpen(false)}
					>
						<span className="sr-only">Close conversations</span>
					</button>
				) : null}

				<main className="workspace" inert={drawerModal || undefined}>
					<TopBar
						phase={phase}
						compact={compact}
						drawerOpen={drawerOpen}
						onOpenRail={openDrawer}
						onSaveChat={canSave ? handleSaveChat : null}
						voice={voice}
					/>

					<div className="stage">
						<div className="thread" ref={threadRef}>
							<div className="thread__inner">
								<div className="hero" inert={phase === "chat" || undefined}>
									<div className="orb orb--hero" aria-hidden="true" />
									<h1 className="hero__title">
										What do you want to learn about money today?
									</h1>
									<p className="hero__sub">
										Ask me about investing, your ASPIRE modules, or the
										programme itself.
									</p>
								</div>

								<section aria-label="Conversation">
									<Transcript
										messages={messages}
										streaming={streaming}
										isThinking={isThinking}
										followUps={followUps}
										onRegenerate={handleRegenerate}
										onAsk={ask}
										playback={{
											available: voice.available,
											playingId: voice.playingId,
											pausedId: voice.pausedId,
											play: voice.play,
										}}
										game={
											game && threadId
												? {
														threadId,
														persona,
														state: game,
														onChanged: setGame,
													}
												: null
										}
									/>
								</section>
							</div>
						</div>

						{voice.phase === "consent" ? (
							<div className="voice-slot">
								<VoiceConsent onAllow={voice.allowMic} onDeny={voice.denyMic} />
							</div>
						) : null}

						{voice.note ? (
							<div className="voice-slot">
								<VoiceNote
									note={voice.note}
									onAction={voice.runNoteAction}
									onDismiss={voice.dismissNote}
								/>
							</div>
						) : null}

						<Composer
							onSend={ask}
							busy={!settled}
							onStop={handleStop}
							simpleMode={simpleMode}
							onToggleSimpleMode={() => setSimpleMode((on) => !on)}
							draft={draft}
							onDraftChange={setDraft}
							voice={voice}
						/>

						<div className="starters">
							<div
								className="starters__row"
								inert={phase === "chat" || undefined}
							>
								{starterPrompts.map((prompt) => (
									<button
										key={prompt}
										type="button"
										className="starter"
										onClick={() => ask(prompt)}
									>
										{prompt}
									</button>
								))}
							</div>
						</div>
					</div>

					{/* The hero h1 goes inert with the hero, so the conversation
					    supplies the page heading once it takes over. */}
					{phase === "chat" ? (
						<h1 className="sr-only">Conversation with ASPIRE AI</h1>
					) : null}

					<output className="sr-only">{announcement}</output>

					<p className="disclaimer">
						ASPIRE AI can make mistakes.{" "}
						<strong>Check important info with your mentor.</strong>
					</p>
				</main>
			</div>
		</div>
	);
}
