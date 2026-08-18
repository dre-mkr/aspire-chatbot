import { useQueryClient } from "@tanstack/react-query";
import { useNavigate, useRouter } from "@tanstack/react-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { AccountControl } from "#/components/auth/AccountControl";
import { Composer } from "#/components/chat/Composer";
import { Rail } from "#/components/chat/Rail";
import { VoiceConsent, VoiceNote } from "#/components/chat/Voice";
import { CloseIcon, MenuIcon } from "#/components/icons";
import { GuideChooser } from "#/components/onboarding/GuideChooser";
import { guideAsked, rememberGuideAsked } from "#/lib/aspire/guide-choice";
import { newThreadId } from "#/lib/aspire/conversations";
import { clearEligibilityResult } from "#/lib/aspire/eligibility";
import { downloadTranscript } from "#/lib/aspire/export";
import {
	readLandingDraft,
	stageFirstTurn,
	stashLandingDraft,
} from "#/lib/aspire/handoff";
import { type StoredConversation, titleFor } from "#/lib/aspire/history";
import { starterPrompts } from "#/lib/aspire/knowledge";
import { upsertConversation } from "#/lib/aspire/queries";
import type { AnswerSearch } from "#/lib/aspire/search";
import { DEFAULT_DOCUMENT_TITLE } from "#/lib/aspire/title";
import { useAnswerSettings } from "#/lib/aspire/use-answer-settings";
import { useConversationList } from "#/lib/aspire/use-conversation-list";
import { useVoice } from "#/lib/aspire/use-voice";

/**
 * The empty state, and nothing else. It has no transcript, no games, and no
 * eligibility card, because it can never have a conversation to put them in.
 *
 * Sending is a handoff rather than a send: the id is minted here, the rail row
 * is committed here, and the question is left for the chat page to ask. That
 * is what keeps this page free of the streaming machinery.
 */
export function LandingScreen() {
	const navigate = useNavigate();
	const router = useRouter();
	const queryClient = useQueryClient();

	/** The three answer settings, read from the address. */
	const {
		simpleMode,
		toggleSimpleMode,
		persona,
		setPersona,
		lang,
		setLanguageInUrl,
		personaNotice,
		dismissPersonaNotice,
	} = useAnswerSettings();

	/**
	 * Who is reading, asked once per browser before the first question.
	 *
	 * Only when nothing has answered it already: a persona in the address or
	 * derived from a signed-in account IS the answer, and asking again would be
	 * asking someone to repeat themselves.
	 */
	const [askGuide, setAskGuide] = useState(false);
	useEffect(() => {
		// After mount, never during render: there is no `localStorage` in SSR,
		// and reading it while rendering would mismatch the server's HTML.
		if (persona === null && !guideAsked()) setAskGuide(true);
	}, [persona]);

	const closeGuide = useCallback(() => {
		rememberGuideAsked();
		setAskGuide(false);
	}, []);

	/** The rail's list and its row actions. No conversation is open here. */
	const { hasHistory, renameChat, regenerateTitle, deleteChat } =
		useConversationList();

	const [drawerOpen, setDrawerOpen] = useState(false);

	// Lifted so a transcript can land here for the user to check before sending.
	const [draft, setDraft] = useState("");

	// Restored in an effect, never in the initialiser: the server renders an
	// empty box, and a different first client render would fail to hydrate.
	//
	// Anything ALREADY in the box wins. Both routes are full-document SSR, so
	// the composer is painted and focusable before React attaches, and this
	// effect used to overwrite whatever had been typed in that window with the
	// stashed draft -- usually nothing. The e2e harness documents the symptom
	// from the outside and works around it by retrying up to four times
	// (`e2e/lib/turn.mjs`), which is the shape of a defect nobody had located.
	//
	// A partial fix, honestly: this recovers the value only if React's
	// hydration left it in place. When React has already reconciled the
	// controlled `value` to empty, there is nothing here to read and the
	// behaviour is exactly what it was -- so this cannot make anything worse,
	// but it is not the whole of T3.4 either.
	useEffect(() => {
		const field = document.getElementById("aspire-composer");
		const typed = field instanceof HTMLTextAreaElement ? field.value : "";
		setDraft(typed || readLandingDraft());
	}, []);
	useEffect(() => {
		stashLandingDraft(draft);
	}, [draft]);

	const voice = useVoice({
		onTranscript: setDraft,
		threadId: null,
		language: lang,
		persona,
		onLanguageChange: setLanguageInUrl,
	});

	/** Bumped whenever the composer should take the cursor. */
	const [focusSignal, setFocusSignal] = useState(1);
	const focusComposer = useCallback(() => setFocusSignal((n) => n + 1), []);

	// Nothing here writes a chat's name, so the tab goes back to the product's.
	useEffect(() => {
		if (typeof document === "undefined") return;
		document.title = DEFAULT_DOCUMENT_TITLE;
	}, []);

	/**
	 * Warms the conversation screen once this one is idle.
	 *
	 * Splitting the two pages took the transcript, the directives and the whole
	 * widget set out of this page's download — but it also moved them onto the
	 * far side of the send button, which is the worst moment to be fetching
	 * anything. Asking for the chunk on idle keeps both: nothing extra in the
	 * first paint's way, and nothing left to fetch by the time a question is
	 * ready. Only the component, never the loader: there is no conversation to
	 * load yet.
	 */
	useEffect(() => {
		if (typeof window === "undefined") return;
		const warm = () => {
			const route = router.routesById["/chat/$chatId"];
			if (route) void router.loadRouteChunk(route);
		};
		// `requestIdleCallback` is still missing on older Safari.
		const idle = window.requestIdleCallback;
		if (idle) {
			const handle = idle(warm, { timeout: 2500 });
			return () => window.cancelIdleCallback?.(handle);
		}
		const timer = setTimeout(warm, 1200);
		return () => clearTimeout(timer);
	}, [router]);

	/**
	 * One press is one conversation, however fast it is repeated. Never
	 * cleared: this page is on its way out, and a second staged turn would
	 * replace the first under a different id, leaving the chat page that is
	 * already navigating to look for a question that is no longer there.
	 */
	const handingOff = useRef(false);

	/**
	 * Opens a conversation and leaves its first question for the chat page.
	 * Both the composer and the starter chips arrive here.
	 */
	const startConversation = useCallback(
		(raw: string) => {
			const text = raw.trim();
			if (!text || handingOff.current) return;
			handingOff.current = true;

			voice.stopPlayback();

			const threadId = newThreadId();
			// Committed now, not when the answer settles: this is the rail's row.
			upsertConversation(queryClient, {
				threadId,
				title: titleFor(text),
				updatedAt: Date.now(),
				messages: [{ role: "user", text }],
			});
			stageFirstTurn({
				threadId,
				question: text,
				simple: simpleMode,
				// Captured here, where it is right: see `PendingTurn.language`.
				language: voice.language,
			});
			// The question has left, so it is not also a draft to come back to.
			stashLandingDraft("");

			void navigate({
				to: "/chat/$chatId",
				params: { chatId: threadId },
				// Carried, not dropped.
				search: (previous: AnswerSearch) => previous,
				replace: true,
				viewTransition: true,
			});
		},
		[navigate, queryClient, simpleMode, voice.language, voice.stopPlayback],
	);

	// Captured on open, not in the effect: by then the workspace is inert and focus has moved.
	const railTrigger = useRef<HTMLElement | null>(null);

	const openDrawer = useCallback(() => {
		railTrigger.current = document.activeElement as HTMLElement | null;
		setDrawerOpen(true);
	}, []);

	// Trap focus and Escape, or Tab walks straight out of the drawer into the page behind it.
	useEffect(() => {
		if (!drawerOpen) return;

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
	}, [drawerOpen]);

	const handleOpenPast = useCallback(
		(conversation: StoredConversation) => {
			setDrawerOpen(false);
			void navigate({
				to: "/chat/$chatId",
				params: { chatId: conversation.threadId },
				search: (previous: AnswerSearch): AnswerSearch => ({
					// "Explain it simply" belongs to the reader, so it survives moving between conversations.
					...previous,
					// Language does not.
					...(conversation.language ? { lang: conversation.language } : {}),
				}),
				viewTransition: true,
			});
		},
		[navigate],
	);

	/** This page is the new chat, so the press is a no-op with a cursor. */
	const startNewChat = useCallback(() => {
		setDrawerOpen(false);
		focusComposer();
	}, [focusComposer]);

	/** Cmd/Ctrl+Shift+O — the same binding both reference products use. */
	useEffect(() => {
		const onKey = (event: KeyboardEvent) => {
			if (!(event.metaKey || event.ctrlKey) || !event.shiftKey) return;
			if (event.code !== "KeyO") return;
			event.preventDefault();
			startNewChat();
		};
		window.addEventListener("keydown", onKey);
		return () => window.removeEventListener("keydown", onKey);
	}, [startNewChat]);

	const handleDeleteConversation = useCallback(
		(conversation: StoredConversation) => {
			clearEligibilityResult(conversation.threadId);
			deleteChat(conversation.threadId);
		},
		[deleteChat],
	);

	const handleSaveConversation = useCallback(
		(conversation: StoredConversation) => {
			downloadTranscript(
				conversation.messages,
				// The conversation's own language when it is known, the interface language otherwise.
				conversation.language ?? voice.language,
			);
		},
		[voice.language],
	);

	return (
		<div
			className="app"
			data-phase="landing"
			data-rail={drawerOpen ? "expanded" : "collapsed"}
		>
			{askGuide ? (
				<GuideChooser
					onChoose={(next) => {
						// `null` is the general option, which is also what
						// `setPersona` takes to mean "no band".
						setPersona(next);
						closeGuide();
					}}
					onSkip={closeGuide}
				/>
			) : null}

			<div className="atmosphere" aria-hidden="true">
				<span />
				<span />
				<span />
				<span />
			</div>

			<div className="frame">
				{/* A drawer at every width here, never a column: there is nothing to sit beside. */}
				<Rail
					collapsed={!drawerOpen}
					unreachable={!drawerOpen}
					activeThreadId={null}
					onToggle={() => setDrawerOpen((open) => !open)}
					onNewChat={startNewChat}
					onOpenPast={handleOpenPast}
					onSaveConversation={handleSaveConversation}
					onRenameConversation={(conversation, title) =>
						renameChat(conversation.threadId, title)
					}
					onRegenerateTitle={(conversation) =>
						regenerateTitle(conversation.threadId)
					}
					onDeleteConversation={handleDeleteConversation}
				/>

				{drawerOpen ? (
					<button
						type="button"
						className="rail-scrim"
						onClick={() => setDrawerOpen(false)}
					>
						<span className="sr-only">Close conversations</span>
					</button>
				) : null}

				<main className="workspace" inert={drawerOpen || undefined}>
					{/* The way to the input without walking the whole page. */}
					<a href="#aspire-composer" className="skip-link">
						Skip to the message box
					</a>

					{/* There is no bar up here to hold it, so it stands on its own. */}
					{hasHistory ? (
						<button
							type="button"
							className="rail-open"
							onClick={openDrawer}
							aria-controls="aspire-rail"
							aria-expanded={drawerOpen}
						>
							<MenuIcon />
							<span className="sr-only">Open conversations</span>
						</button>
					) : null}

					{/* The way into an account, whenever the sidebar is not there to carry it. */}
					{/* `inert` as well as the CSS, because they cover different people. */}
					<div
						className="account-slot"
						data-shown={!drawerOpen || undefined}
						inert={drawerOpen || undefined}
					>
						<AccountControl variant="corner" />
					</div>

					<div className="stage">
						<div className="thread">
							<div className="thread__inner">
								<div className="hero">
									<div className="orb orb--hero" aria-hidden="true" />
									<h1 className="hero__title">
										What do you want to learn about money today?
									</h1>
									<p className="hero__sub">
										Ask me about investing, your ASPIRE modules, or the
										programme itself.
									</p>
								</div>
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

						{/* Sits in the voice-note slot, directly above the picker that caused it. */}
						{personaNotice ? (
							<div className="voice-slot">
								<output className="voice-note" data-tone="warn">
									<span className="voice-note__text">{personaNotice}</span>
									<button
										type="button"
										className="icon-btn icon-btn--sm"
										onClick={dismissPersonaNotice}
									>
										<CloseIcon />
										<span className="sr-only">Dismiss</span>
									</button>
								</output>
							</div>
						) : null}

						<Composer
							onSend={startConversation}
							busy={false}
							onStop={() => {}}
							simpleMode={simpleMode}
							onToggleSimpleMode={toggleSimpleMode}
							persona={persona}
							onPersonaChange={setPersona}
							draft={draft}
							onDraftChange={setDraft}
							focusSignal={focusSignal}
							voice={voice}
						/>

						<div className="starters">
							<div className="starters__row">
								{starterPrompts.map((prompt) => (
									<button
										key={prompt}
										type="button"
										className="starter"
										onClick={() => startConversation(prompt)}
									>
										{prompt}
									</button>
								))}
							</div>
						</div>
					</div>

					{/* One text node: as two, the flex gap made "can" and "make" run together when copied. */}
					<p className="disclaimer">ASPIRE AI can make mistakes.</p>
				</main>
			</div>
		</div>
	);
}
