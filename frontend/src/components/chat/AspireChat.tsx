import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useRouterState, useSearch } from "@tanstack/react-router";
import {
	useCallback,
	useEffect,
	useLayoutEffect,
	useMemo,
	useRef,
	useState,
} from "react";
import { AccountControl } from "#/components/auth/AccountControl";
import { CloseIcon, MenuIcon } from "#/components/icons";
import {
	clearEligibilityResult,
	type EligibilityState,
	loadEligibilityResult,
} from "#/lib/aspire/eligibility";
import { downloadTranscript } from "#/lib/aspire/export";
import { type GameState, startGame } from "#/lib/aspire/games";
import {
	displayTitle,
	type StoredConversation,
	titleFor,
} from "#/lib/aspire/history";
import { answerToText, starterPrompts } from "#/lib/aspire/knowledge";
import {
	asPersonaId,
	type PersonaId,
	personaById,
} from "#/lib/aspire/personas";
import {
	conversationQuery,
	eligibilityStateQuery,
	gameStateQuery,
	invalidateAfterTurn,
	readConversation,
} from "#/lib/aspire/queries";
import { useConversation } from "#/lib/aspire/use-conversation";
import { useSession } from "#/lib/aspire/use-session";
import { useVoice } from "#/lib/aspire/use-voice";
import { onPersonaRefused } from "#/lib/stream/session";
import { useMediaQuery } from "#/lib/use-media-query";
import type { ShellSearch } from "#/routes/_shell";
import { ChatTitleBar } from "./ChatTitleBar";
import { Composer } from "./Composer";
import { Rail } from "./Rail";
import { Transcript } from "./Transcript";
import { VoiceConsent, VoiceNote } from "./Voice";

/** The one route that carries a conversation id. */
const CHAT_PREFIX = "/chat/";
/** Below this the rail stops being a column and becomes a modal drawer. */
const COMPACT = "(max-width: 860px)";
/** How far from the bottom still counts as "following along". */
const STICK_THRESHOLD_PX = 160;
/** The playback id the eligibility card speaks under. */
const ELIGIBILITY_SPEECH_ID = -1;

export function AspireChat() {
	// Read-aloud has to start the moment an answer lands, but the voice layer needs the thread id the conversation…
	const speakArrival = useRef<(id: number, text: string) => void>(() => {});

	const navigate = useNavigate();
	const queryClient = useQueryClient();
	/** Which conversation the URL is pointing at, or undefined at `/`. */
	const pathname = useRouterState({ select: (s) => s.location.pathname });
	const chatId = pathname.startsWith(CHAT_PREFIX)
		? decodeURIComponent(pathname.slice(CHAT_PREFIX.length))
		: undefined;

	/** A chat that has been minted and navigated to, but whose URL has not landed. */
	const awaitingUrl = useRef<string | null>(null);
	/** One press of "New chat" is one navigation, however fast it is repeated. */
	const startingNew = useRef(false);

	/** The two answer settings, read from the address rather than from state. */
	const {
		simple,
		persona: personaParam,
		lang,
	} = useSearch({ from: "/_shell" });

	/** The persona the signed-in account resolves to, derived server-side. */
	const { session } = useSession();
	const accountPersona =
		session?.accountType === "registered" ? asPersonaId(session.persona) : null;
	const persona = personaParam ?? accountPersona ?? null;
	/** The language each eligibility check opened in, by thread. */
	const checkLanguage = useRef(new Map<string, string>());

	/**
	 * The live game's identity and score. The summary is the authority on the
	 * numbers; the card closing (`onChanged(null)`) is what sends them, so the
	 * agent's next turn can reference what the child actually scored.
	 */
	const liveGame = useRef<{
		gameType: string;
		concept: string;
		solved: number;
		total: number;
		duration_s: number;
		completed: boolean;
		reported: boolean;
	} | null>(null);

	const {
		phase,
		messages,
		streaming,
		isThinking,
		followUps,
		hasHistory,
		activeStoredTitle,
		threadId,
		animateAfterId,
		send,
		sendInteraction,
		sendUploadResult,
		sendGameResult,
		regenerate,
		stop,
		openPast,
		reset,
		renameChat,
		regenerateTitle,
		deleteChat,
	} = useConversation({
		onAnswer: (id, text) => speakArrival.current(id, text),
		persona,
		// Titles are written in the language the interface is set to, read from the existing voice setting rather than…
		getLanguage: () => voice.language,
		// The first message of a chat gives it an address.
		onGameStart: (id, gameType, concept) => {
			setGame(null);
			liveGame.current = {
				gameType,
				concept,
				solved: 0,
				total: 0,
				duration_s: 0,
				completed: false,
				reported: false,
			};
			// START the game — the directive names it, the engine owns it. The state
			// poll alone can never start one, which is exactly how the card used to
			// sit on "{active:false}" forever. If the agent's own tools already
			// started it server-side, the start declines and the state fetch wins.
			const engineName =
				{ scramble: "word_scramble", true_false: "true_false" }[gameType] ??
				gameType;
			void startGame(id, { game_type: engineName })
				.then((state) => {
					if (state) setGame(state);
				})
				.catch(() =>
					queryClient
						.fetchQuery({ ...gameStateQuery(id), staleTime: 0 })
						.then((state) => {
							if (state) setGame(state);
						})
						.catch(() => undefined),
				);
		},
		// The card carries the whole turn, so it is fetched rather than taken from the chat response: the eligibility e…
		onEligibilityStart: (id, language) => {
			clearEligibilityResult(id);
			setEligibility(null);
			// The language the check opened in, captured here and not read again.
			checkLanguage.current.set(id, language);
			// Same treatment, same reason as the game turn above.
			void queryClient
				.fetchQuery({ ...eligibilityStateQuery(id, language), staleTime: 0 })
				.then((state) => {
					if (state.active) setEligibility(state);
				})
				.catch(() => undefined);
		},
		onThreadStart: (id) => {
			awaitingUrl.current = id;
			void navigate({
				to: "/chat/$chatId",
				params: { chatId: id },
				// Carried, not dropped.
				search: (previous: ShellSearch) => previous,
				replace: true,
			});
		},
	});

	const compact = useMediaQuery(COMPACT);
	const [railCollapsed, setRailCollapsed] = useState(false);
	const [drawerOpen, setDrawerOpen] = useState(false);

	const simpleMode = simple === true;
	const toggleSimpleMode = useCallback(() => {
		void navigate({
			to: ".",
			// Spread, not replace.
			search: (previous: ShellSearch): ShellSearch =>
				previous.simple
					? { ...previous, simple: undefined }
					: { ...previous, simple: true },
			replace: true,
		});
	}, [navigate]);

	// `replace`, like the toggle above and for the same reason: choosing who is at the screen adjusts the current v…
	const setPersona = useCallback(
		(next: PersonaId | null) => {
			void navigate({
				to: ".",
				search: (previous: ShellSearch): ShellSearch => ({
					...previous,
					persona: next ?? undefined,
				}),
				replace: true,
			});
		},
		[navigate],
	);

	/** A persona the server would not grant, said out loud and then corrected. */
	const [personaNotice, setPersonaNotice] = useState<string | null>(null);
	useEffect(() => {
		return onPersonaRefused(({ requested, granted }) => {
			const grantedId = asPersonaId(granted);
			const requestedName =
				personaById(asPersonaId(requested))?.name ?? requested;
			const grantedName = personaById(grantedId)?.name ?? granted;
			setPersonaNotice(
				`${requestedName} is not available on this account, so answers stay with ${grantedName}.`,
			);
			// Corrected rather than left disagreeing with the session.
			setPersona(grantedId);
		});
	}, [setPersona]);

	// Lifted so a transcript can land here for the user to check before sending.
	const [draft, setDraft] = useState("");

	// `replace`, like the other two answer settings: switching language adjusts the current view rather than going…
	const setLanguageInUrl = useCallback(
		(next: "en" | "es" | "fr") => {
			void navigate({
				to: ".",
				search: (previous: ShellSearch): ShellSearch => ({
					...previous,
					lang: next,
				}),
				replace: true,
			});
		},
		[navigate],
	);

	const voice = useVoice({
		onTranscript: setDraft,
		threadId,
		language: lang,
		onLanguageChange: setLanguageInUrl,
	});

	// Only new answers are spoken.
	useEffect(() => {
		speakArrival.current = (id, text) => {
			if (voice.autoSpeak && voice.available) void voice.play(id, text);
		};
	}, [voice.autoSpeak, voice.available, voice.play]);

	const threadRef = useRef<HTMLDivElement>(null);

	// The game lives on the server, keyed by this thread.
	const [game, setGame] = useState<GameState | null>(null);
	/** The eligibility card's state. */
	const [eligibility, setEligibility] = useState<EligibilityState | null>(null);
	const settled = !isThinking && !streaming;

	/** The server's answer for this thread's game, cached by Query. */
	const gameQuery = useQuery(gameStateQuery(threadId, settled));

	// Adopt, never clear.
	useEffect(() => {
		if (gameQuery.data) setGame(gameQuery.data);
	}, [gameQuery.data]);

	/** Restores the eligibility card, from whichever half still holds it. */
	const eligibilityQuery = useQuery(
		// The captured language, not the live one.
		eligibilityStateQuery(
			threadId,
			(threadId ? checkLanguage.current.get(threadId) : undefined) ??
				voice.language,
			settled,
		),
	);

	/** The completion handoff. */
	const wasSettled = useRef(settled);
	useEffect(() => {
		const justSettled = settled && !wasSettled.current;
		wasSettled.current = settled;
		if (justSettled) invalidateAfterTurn(queryClient, threadId);
	}, [settled, threadId, queryClient]);

	useEffect(() => {
		const state = eligibilityQuery.data;
		if (!state || !threadId) return;

		if (state.active) {
			setEligibility(state);
			return;
		}

		// Server says no session.
		const stored = loadEligibilityResult(threadId);
		if (!stored) return;
		setEligibility({
			active: false,
			language: stored.language,
			question: null,
			result: stored.result,
			answered: 0,
			total: 0,
			labels: stored.labels,
		});
	}, [eligibilityQuery.data, threadId]);

	// The rail is a drawer whenever it has nowhere to sit as a column: on a narrow screen, and on the landing scree…
	const drawerMode = compact || phase === "landing";
	const railClosed = drawerMode ? !drawerOpen : railCollapsed;
	const drawerModal = drawerMode && drawerOpen;

	// Announce discrete events, not the stream.
	const latest = messages.at(-1);
	const announcement =
		isThinking || streaming
			? "ASPIRE AI is writing a reply."
			: latest?.role === "game"
				? "A game has started. The game card is below."
				: latest?.role === "eligibility"
					? "The ASPIRE eligibility check has started. The card is below."
					: latest?.role === "error"
						? latest.text
						: latest?.role === "assistant"
							? answerToText(latest.blocks)
							: "";

	/** Where each conversation was left, keyed by thread. */
	const scrollTops = useRef(new Map<string, number>());
	/** True while the restore below is assigning an offset. */
	const restoring = useRef(false);
	/** `""` is the new chat, which has no id and cannot collide with one. */
	const scrollKey = threadId ?? "";

	/** Which thread the follow-the-stream effect is currently chasing. */
	const following = useRef<string | null>(null);

	// Follow the answer as it streams, but only while the reader is already at the bottom — scrolling up to re-read…
	// biome-ignore lint/correctness/useExhaustiveDependencies: change trigger
	useEffect(() => {
		const thread = threadRef.current;
		if (!thread || phase !== "chat") return;

		// A different conversation just arrived.
		if (following.current !== threadId) {
			following.current = threadId;
			return;
		}

		const distance =
			thread.scrollHeight - thread.scrollTop - thread.clientHeight;
		if (distance < STICK_THRESHOLD_PX) {
			thread.scrollTop = thread.scrollHeight;
		}
	}, [messages, streaming, isThinking, phase, threadId]);

	// Restore before paint, so a reopened conversation is never briefly shown at the wrong offset.
	const restoredFor = useRef<string | null>(null);
	useLayoutEffect(() => {
		const thread = threadRef.current;
		if (!thread || !threadId) return;
		if (restoredFor.current === threadId) return;
		// Nothing to measure against yet; wait for the transcript to render.
		if (messages.length === 0) return;

		restoredFor.current = threadId;
		const saved = scrollTops.current.get(threadId);
		// Suppress the `scroll` this assignment provokes, so restoring a position cannot overwrite the position being r…
		restoring.current = true;
		thread.scrollTop = saved ?? thread.scrollHeight;
		requestAnimationFrame(() => {
			restoring.current = false;
		});
	}, [threadId, messages]);

	/** One unsent draft per conversation. */
	const drafts = useRef(new Map<string, string>());
	const draftKey = useRef("");
	const liveDraft = useRef(draft);

	// Declared before the swap below so that, on the commit where the thread changes, the value being banked is the…
	useEffect(() => {
		liveDraft.current = draft;
	}, [draft]);

	useEffect(() => {
		if (scrollKey === draftKey.current) return;
		drafts.current.set(draftKey.current, liveDraft.current);
		draftKey.current = scrollKey;
		setDraft(drafts.current.get(scrollKey) ?? "");
	}, [scrollKey]);

	// Captured when the drawer is opened, not when the effect runs: by then the workspace is already inert and the…
	const railTrigger = useRef<HTMLElement | null>(null);

	const openDrawer = useCallback(() => {
		railTrigger.current = document.activeElement as HTMLElement | null;
		setDrawerOpen(true);
	}, []);

	// A drawer that leaves the page behind it reachable is not a drawer: Tab walks straight out of it and into the…
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
		if (drawerMode) setDrawerOpen((open) => !open);
		else setRailCollapsed((collapsed) => !collapsed);
	}, [drawerMode]);

	// Asking something new, reopening a conversation, or starting a fresh one all make whatever is being read aloud…
	const { stopPlayback } = voice;

	// simpleMode is read at send time rather than captured per conversation, so toggling it changes the next answer…
	const ask = useCallback(
		(question: string) => {
			stopPlayback();
			send(question, simpleMode);
		},
		[send, simpleMode, stopPlayback],
	);

	/** What a directive needs in order to be interactive. */
	const directiveContext = useMemo(
		() => ({
			threadId: threadId ?? undefined,
			send: ask,
			onWidgetInteraction: sendInteraction,
			// Sent through its own channel (`/v2/game/result`), not as prose: the score rides on `safety_flags` server-side…
			onGameResult: sendGameResult,
			onUpload: (
				_slot: string,
				result: { document_id: string; mime: string; size_bytes: number },
			) => sendUploadResult(result),
			onEditSlot: (slot: string) => ask(`I need to change ${slot}.`),
			onSubmit: () => ask("Submit my application."),
			onSpeak: (text: string) => voice.play(ELIGIBILITY_SPEECH_ID, text),
			speakAvailable: voice.available,
			locale: voice.language,
		}),
		[
			threadId,
			ask,
			sendInteraction,
			sendUploadResult,
			sendGameResult,
			voice.play,
			voice.available,
			voice.language,
		],
	);

	// Carries the id of the answer being retried, so it replaces that one rather than whatever happens to be last i…
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

	/** Bumped whenever the composer should take the cursor. */
	const [focusSignal, setFocusSignal] = useState(1);
	const focusComposer = useCallback(() => setFocusSignal((n) => n + 1), []);

	/** Makes the conversation match the URL, in one direction only. */
	useEffect(() => {
		// A chat has been started but the router has not committed its URL yet.
		if (awaitingUrl.current) {
			if (chatId === awaitingUrl.current) awaitingUrl.current = null;
			return;
		}

		if (!chatId) {
			startingNew.current = false;
			if (threadId || messages.length > 0) {
				stopPlayback();
				setGame(null);
				setEligibility(null);
				reset();
			}
			return;
		}

		if (chatId === threadId) return;

		// Read from the cache first, and that is not an optimisation.
		const cached = readConversation(queryClient, chatId);
		if (cached && cached.messages.length > 0) {
			stopPlayback();
			setGame(null);
			// Cleared rather than carried across: the restore effect above reads the new thread's own card, and showing the…
			setEligibility(null);
			openPast(cached);
			return;
		}

		let live = true;
		void queryClient
			.ensureQueryData(conversationQuery(chatId))
			.then((stored) => {
				if (!live) return;
				stopPlayback();
				setGame(null);
				setEligibility(null);
				openPast(stored);
			})
			.catch(() => {
				// An address for a conversation this account does not have: a link from another device, a cleared identity, a h…
				if (!live) return;
				void navigate({
					to: "/",
					search: (previous: ShellSearch) => previous,
					replace: true,
				});
			});
		return () => {
			live = false;
		};
	}, [
		chatId,
		threadId,
		messages.length,
		navigate,
		openPast,
		reset,
		stopPlayback,
		queryClient,
	]);

	const handleOpenPast = useCallback(
		(conversation: StoredConversation) => {
			setDrawerOpen(false);
			void navigate({
				to: "/chat/$chatId",
				params: { chatId: conversation.threadId },
				search: (previous: ShellSearch): ShellSearch => ({
					// "Explain it simply" belongs to the reader, not to the conversation, so it survives moving between them — exac…
					...previous,
					// Language does not.
					...(conversation.language ? { lang: conversation.language } : {}),
				}),
			});
		},
		[navigate],
	);

	const startNewChat = useCallback(() => {
		// Already on an empty new chat: this is a no-op with a cursor.
		if (!chatId && messages.length === 0) {
			setDrawerOpen(false);
			focusComposer();
			return;
		}
		if (startingNew.current) return;
		startingNew.current = true;

		// A deliberate move to the empty state outranks a first send that is still settling, so the gap-holder is dropp…
		awaitingUrl.current = null;
		stopPlayback();
		setDrawerOpen(false);
		void navigate({ to: "/", search: (previous: ShellSearch) => previous });
		focusComposer();
	}, [chatId, messages.length, focusComposer, navigate, stopPlayback]);

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

	/** Writes out one conversation from the rail. */
	/** What the open conversation is called. */
	// biome-ignore lint/correctness/useExhaustiveDependencies: activeStoredTitle is the trigger
	const activeTitle = useMemo(() => {
		const stored = threadId
			? readConversation(queryClient, threadId)
			: undefined;
		if (stored) return displayTitle(stored);

		// Nothing is stored yet -- the first answer is still arriving, so there is no thread id and no record.
		const firstQuestion = messages.find((m) => m.role === "user");
		return firstQuestion?.role === "user" ? titleFor(firstQuestion.text) : "";
	}, [threadId, activeStoredTitle, messages]);

	// Browser tabs and history entries should say which chat this is.
	useEffect(() => {
		if (typeof document === "undefined") return;
		document.title = activeTitle
			? `${activeTitle} · ASPIRE AI`
			: "ASPIRE AI · Financial literacy assistant";
	}, [activeTitle]);

	/** Deletes one conversation, and leaves it if it is the one on screen. */
	const handleDeleteConversation = useCallback(
		(conversation: StoredConversation) => {
			const open = conversation.threadId === threadId;

			clearEligibilityResult(conversation.threadId);
			drafts.current.delete(conversation.threadId);
			deleteChat(conversation.threadId);

			if (!open) return;
			setDrawerOpen(false);
			// Everything else follows from the address: no chat id means the reconciler stops the audio, drops the cards, a…
			void navigate({
				to: "/",
				search: (previous: ShellSearch) => previous,
				replace: true,
			});
		},
		[threadId, deleteChat, navigate],
	);

	const handleSaveConversation = useCallback(
		(conversation: StoredConversation) => {
			const live = conversation.threadId === threadId && messages.length > 0;
			downloadTranscript(
				live ? messages : conversation.messages,
				// The conversation's own language when it is known, the interface language otherwise.
				conversation.language ?? voice.language,
			);
		},
		[messages, threadId, voice.language],
	);

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
					unreachable={drawerMode && !drawerOpen}
					activeThreadId={threadId}
					onToggle={toggleRail}
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
					{/* The way to the input without walking the whole conversation. */}
					<a href="#aspire-composer" className="skip-link">
						Skip to the message box
					</a>
					{/* The top bar is gone. */}
					{/* Only on the landing screen, where there is no bar to hold it. */}
					{phase === "landing" && hasHistory ? (
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
						data-shown={railClosed || undefined}
						inert={!railClosed || undefined}
					>
						<AccountControl variant="corner" />
					</div>

					{/* No bar on the empty state: the hero already carries the product's identity, and a bar saying "New chat" above… */}
					{phase === "chat" ? (
						<ChatTitleBar
							title={activeTitle}
							showDrawerTrigger={drawerMode}
							drawerOpen={drawerOpen}
							onOpenRail={openDrawer}
							onRename={(title) => {
								if (threadId) renameChat(threadId, title);
							}}
						/>
					) : null}

					<div className="stage">
						<div
							className="thread"
							ref={threadRef}
							// Banked continuously rather than on the way out: a chat can also be left by the back button or a keyboard shor…
							onScroll={(event) => {
								// Not while a restore is mid-assignment: that event is this component's own, and banking it overwrites the posi…
								if (restoring.current) return;
								scrollTops.current.set(
									scrollKey,
									event.currentTarget.scrollTop,
								);
							}}
						>
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
										animateAfterId={animateAfterId}
										scrollRef={threadRef}
										onRegenerate={handleRegenerate}
										onAsk={ask}
										playback={{
											available: voice.available,
											playingId: voice.playingId,
											pausedId: voice.pausedId,
											play: voice.play,
										}}
										directiveContext={directiveContext}
										game={
											game && threadId
												? {
														threadId,
														state: game,
														onChanged: (state: GameState | null) => {
															const live = liveGame.current;
															if (state && live) {
																live.solved = state.solved;
																live.total = state.prompt.total;
															}
															// Null means the card closed; report the real
															// numbers once, through the game-result channel.
															if (!state && live && !live.reported) {
																live.reported = true;
																sendGameResult({
																	game: live.gameType,
																	concept_id: live.concept,
																	score: live.solved,
																	max_score: Math.max(1, live.total),
																	duration_s: live.duration_s,
																	completed: live.completed,
																});
															}
															setGame(state);
														},
														onSummary: (summary) => {
															const live = liveGame.current;
															if (!live) return;
															live.solved = summary.solved;
															live.total = Math.max(1, summary.total);
															live.duration_s = Math.max(
																0,
																Math.round(summary.duration_seconds),
															);
															live.completed = true;
														},
													}
												: null
										}
										eligibility={
											eligibility && threadId
												? {
														threadId,
														state: eligibility,
														onChanged: setEligibility,
														// Speaks the question, or the verdict.
														onSpeak: (text) =>
															voice.play(ELIGIBILITY_SPEECH_ID, text),
														speakAvailable: voice.available,
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

						{/* Sits directly above the picker that caused it, in the slot the voice notes use — the control and the explanat… */}
						{personaNotice ? (
							<div className="voice-slot">
								<output className="voice-note" data-tone="warn">
									<span className="voice-note__text">{personaNotice}</span>
									<button
										type="button"
										className="icon-btn icon-btn--sm"
										onClick={() => setPersonaNotice(null)}
									>
										<CloseIcon />
										<span className="sr-only">Dismiss</span>
									</button>
								</output>
							</div>
						) : null}

						<Composer
							onSend={ask}
							busy={!settled}
							onStop={handleStop}
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

					{/* The hero h1 goes inert with the hero, so the conversation supplies the page heading once it takes over. */}
					{phase === "chat" ? (
						<h1 className="sr-only">Conversation with ASPIRE AI</h1>
					) : null}

					<output className="sr-only">{announcement}</output>

					{/* One text node: split across an element the space between "can" and
					    "make" came from a flex gap, so the copied and spoken line ran the
					    two words together. */}
					<p className="disclaimer">ASPIRE AI can make mistakes.</p>
				</main>
			</div>
		</div>
	);
}
