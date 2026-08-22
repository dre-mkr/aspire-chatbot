import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams } from "@tanstack/react-router";
import {
	useCallback,
	useEffect,
	useLayoutEffect,
	useMemo,
	useRef,
	useState,
} from "react";
import { AccountControl } from "#/components/auth/AccountControl";
import { CloseIcon } from "#/components/icons";
import { fetchConversation } from "#/lib/aspire/conversations";
import {
	clearEligibilityResult,
	type EligibilityState,
	loadEligibilityResult,
} from "#/lib/aspire/eligibility";
import { downloadTranscript } from "#/lib/aspire/export";
import { engineGameType } from "#/lib/aspire/game-kinds";
import { type GameState, startGame } from "#/lib/aspire/games";
import {
	isFreshThread,
	type PendingTurn,
	takePendingTurn,
} from "#/lib/aspire/handoff";
import {
	displayTitle,
	loadConversations,
	type StoredConversation,
	titleFor,
} from "#/lib/aspire/history";
import type { HookLanguage } from "#/lib/aspire/hooks";
import { answerToText } from "#/lib/aspire/knowledge";
import { displayName } from "#/lib/aspire/persona-name";
import {
	eligibilityStateQuery,
	gameStateQuery,
	invalidateAfterTurn,
	readConversation,
	upsertConversation,
} from "#/lib/aspire/queries";
import type { AnswerSearch } from "#/lib/aspire/search";
import { ensureSession } from "#/lib/aspire/session";
import { DEFAULT_DOCUMENT_TITLE } from "#/lib/aspire/title";
import { useAnswerSettings } from "#/lib/aspire/use-answer-settings";
import { useConversation } from "#/lib/aspire/use-conversation";
import { useSession } from "#/lib/aspire/use-session";
import { useVoice } from "#/lib/aspire/use-voice";
import { useMediaQuery } from "#/lib/use-media-query";
import { AgeBandProvider, bandForPersona } from "./AgeBandProvider";
import { ChatTitleBar } from "./ChatTitleBar";
import { ChatWelcome } from "./ChatWelcome";
import { Composer } from "./Composer";
import { FirstRun } from "./FirstRun";
import { LanguageSwitcher } from "./LanguageSwitcher";
import { Rail } from "./Rail";
import { Transcript } from "./Transcript";
import { VoiceConsent, VoiceNote } from "./Voice";

/** Below this the rail stops being a column and becomes a modal drawer. */
const COMPACT = "(max-width: 860px)";
/** How far from the bottom still counts as "following along". */
const STICK_THRESHOLD_PX = 160;
/** The playback id the eligibility card speaks under. */
const ELIGIBILITY_SPEECH_ID = -1;

/**
 * One conversation, and nothing else. The landing screen is a separate page:
 * it mints the conversation and stages its first question, and this page is
 * what sends it.
 */
export function ChatScreen() {
	// A ref: onAnswer is needed now, but voice needs the threadId useConversation returns.
	const speakArrival = useRef<(id: number, text: string) => void>(() => {});

	const navigate = useNavigate();
	const queryClient = useQueryClient();
	/** Which conversation the URL is pointing at. The only source of truth for it. */
	const chatId = useParams({
		from: "/chat/$chatId",
		select: (params) => params.chatId,
	});

	/** The three answer settings, read from the address. */
	const {
		simpleMode,
		toggleSimpleMode,
		persona,
		band,
		setPersona,
		lang,
		setLanguageInUrl,
		personaNotice,
		dismissPersonaNotice,
	} = useAnswerSettings();

	/** Read only for the orb's colour: the band is what separates Skye from Kaleb. */
	const { session: identity } = useSession();

	/**
	 * What the reader calls this assistant, for the parts only a screen reader
	 * hears. `displayName` mirrors the server's `names.py` and falls back to
	 * "ASPIRE AI" when no persona has given it a name -- which is Guest, and is
	 * correct there.
	 */
	const guideName = displayName(persona, band ?? identity?.ageBand);

	/**
	 * How many conversations this reader already has, for the welcome's opening
	 * line. Read once on mount rather than subscribed: it decides between "Hi
	 * there" and "Welcome back", and a greeting that changed mid-session because
	 * a conversation was saved behind it would be worse than either.
	 *
	 * localStorage is unavailable during SSR, hence the effect rather than an
	 * initialiser -- the first paint says "Hi there" and corrects itself, which
	 * is the right way round for a reader who has never been here.
	 */
	const [priorConversations, setPriorConversations] = useState(0);
	useEffect(() => {
		setPriorConversations(loadConversations().length);
	}, []);

	/** The language each eligibility check opened in, by thread. */
	const checkLanguage = useRef(new Map<string, string>());

	/** The live game's score; the card closing (`onChanged(null)`) is what reports it. */
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
		messages,
		streaming,
		isThinking,
		followUps,
		activeStoredTitle,
		threadId,
		animateAfterId,
		adoptThread,
		send,
		resumeFirstTurn,
		sendInteraction,
		sendUploadResult,
		sendGameResult,
		regenerate,
		stop,
		openPast,
		renameChat,
		regenerateTitle,
		deleteChat,
	} = useConversation({
		onAnswer: (id, text) => speakArrival.current(id, text),
		persona,
		// The band travels with the persona, because for `stella` it IS the
		// persona as far as the reader is concerned: Skye at 5-8, Kaleb at 9-12.
		// It was already in the URL and already driving the orb's colour; the
		// turn itself was the one place it never reached.
		band,
		// Titles follow the interface language, read at call time since voice is built below.
		getLanguage: () => voice.language,
		getAutoLanguage: () => voice.autoLanguage,
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
			// Start it here: the state poll alone never starts one, so the card sat inactive forever.
			const engineName = engineGameType(gameType);
			// The persona is what selects the age-appropriate item set. Omitting it
			// meant the engine's own filter never ran, so a five-year-old on Stella
			// was served the Orion set -- compound interest, 5% returns, "no more
			// than 25% in any one sector" -- while the set written for her was
			// unreachable. The filter was always correct; nothing was calling it.
			void startGame(id, { game_type: engineName, persona, age_band: band })
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
		// The card carries the whole turn, so it is fetched rather than read off the chat response.
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
	});

	const compact = useMediaQuery(COMPACT);
	const [railCollapsed, setRailCollapsed] = useState(false);
	const [drawerOpen, setDrawerOpen] = useState(false);

	// Lifted so a transcript can land here for the user to check before sending.
	const [draft, setDraft] = useState("");

	const voice = useVoice({
		onTranscript: setDraft,
		threadId,
		language: lang,
		persona,
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

	// The rail is a drawer only where it cannot sit as a column.
	const railClosed = compact ? !drawerOpen : railCollapsed;
	const drawerModal = compact && drawerOpen;

	/**
	 * Announce discrete events, not the stream. The one status region in the app.
	 *
	 * There were two of these, here and in `Transcript`, and both put the whole
	 * settled answer into a polite region — so every answer was read out twice,
	 * end to end, with no way to stop the second pass. This is the survivor
	 * because it is the only one that knows about games and the eligibility
	 * check; the wording is the other one's, which was better.
	 *
	 * Silent while tokens arrive: "Finding an answer." already stands, and
	 * interrupting it every few hundred milliseconds says nothing new.
	 */
	const latest = messages.at(-1);
	const announcement = streaming
		? ""
		: isThinking
			? "Finding an answer."
			: latest?.role === "game"
				? "A game has started. The game card is below."
				: latest?.role === "eligibility"
					? "The ASPIRE eligibility check has started. The card is below."
					: latest?.role === "error"
						? latest.text
						: latest?.role === "assistant"
							? `Answer ready. ${answerToText(latest.blocks)}`
							: "";

	/** Where each conversation was left, keyed by thread. */
	const scrollTops = useRef(new Map<string, number>());
	/** True while the restore below is assigning an offset. */
	const restoring = useRef(false);
	/** `""` is a thread not yet adopted, which cannot collide with an id. */
	const scrollKey = threadId ?? "";

	/** Which thread the follow-the-stream effect is currently chasing. */
	const following = useRef<string | null>(null);

	// Follow the stream only from the bottom; scrolling up to re-read must not be yanked back.
	// biome-ignore lint/correctness/useExhaustiveDependencies: change trigger
	useEffect(() => {
		const thread = threadRef.current;
		if (!thread) return;

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
	}, [messages, streaming, isThinking, threadId]);

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
		// Suppress the `scroll` this fires, or the restore overwrites the offset being restored.
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

	// Runs before the swap below, so the draft banked on a thread change is the outgoing one.
	useEffect(() => {
		liveDraft.current = draft;
	}, [draft]);

	useEffect(() => {
		if (scrollKey === draftKey.current) return;
		drafts.current.set(draftKey.current, liveDraft.current);
		draftKey.current = scrollKey;
		setDraft(drafts.current.get(scrollKey) ?? "");
	}, [scrollKey]);

	// Captured on open, not in the effect: by then the workspace is inert and focus has moved.
	const railTrigger = useRef<HTMLElement | null>(null);

	const openDrawer = useCallback(() => {
		railTrigger.current = document.activeElement as HTMLElement | null;
		setDrawerOpen(true);
	}, []);

	// Trap focus and Escape, or Tab walks straight out of the drawer into the page behind it.
	useEffect(() => {
		if (!drawerModal) return;

		// `:not([inert])`, because the first button in the rail is `.rail__mark`
		// — the A that toggles it — and that one is inert exactly when the drawer
		// is open. Focusing it did nothing, so opening the drawer dropped focus
		// on `<body>` and Tab restarted at the top of the page behind it.
		document
			.getElementById("aspire-rail")
			?.querySelector<HTMLElement>("button:not([inert])")
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

	// Asking, reopening, or starting a chat all make the current read-aloud stale.
	const { stopPlayback } = voice;

	// simpleMode is read at send time, so toggling it changes the next answer, not past ones.
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
			// Own channel (`/v2/game/result`), not prose: the score rides on `safety_flags` server-side.
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

	// Carries the retried answer's id, so it replaces that one and not whatever is last.
	//
	// `simple` is the per-answer "Simpler" button forcing the plain-words pass on
	// for this one re-ask; without it the composer toggle decides, as before.
	const handleRegenerate = useCallback(
		(messageId: number, simple?: boolean) => {
			stopPlayback();
			regenerate(messageId, simple ?? simpleMode);
		},
		[regenerate, simpleMode, stopPlayback],
	);

	const handleStop = useCallback(() => {
		stopPlayback();
		stop();
	}, [stop, stopPlayback]);

	/**
	 * Which conversation this page has already gone to open. A ref, and not
	 * `threadId`, because it has to be true the instant the work starts: the
	 * callbacks below are rebuilt when the voice layer loads its preferences,
	 * which re-runs this effect a tick later, while `threadId` is still the
	 * state it was before. Guarding on state alone let that second run walk
	 * past a first turn it had already sent and restore the cached row over
	 * the top of it.
	 */
	const openedFor = useRef<string | null>(null);

	/** The claimed first question, waiting for a mount that will last. */
	const firstTurn = useRef<PendingTurn | null>(null);
	/** Bumped once a first question has been claimed and is ready to go out. */
	const [armed, setArmed] = useState(0);

	/**
	 * Sends the handed-off question, one commit after it was claimed.
	 *
	 * The router re-commits this page as it finishes its navigation, so the
	 * mount effects run, are torn down, and run again — with refs intact, and
	 * before any state from the first pass has landed. `useConversation` ends
	 * whatever is in flight when it is torn down, so a turn started during the
	 * mount commit is aborted in that gap and arrives as "that took too long".
	 * Waiting for `armed` to land puts the request past it.
	 */
	useEffect(() => {
		if (armed === 0) return;
		const turn = firstTurn.current;
		if (!turn) return;
		firstTurn.current = null;
		resumeFirstTurn(turn.threadId, turn.question, turn.simple, turn.language);
	}, [armed, resumeFirstTurn]);

	/** Makes the conversation match the URL, in one direction only. */
	useEffect(() => {
		if (openedFor.current === chatId) return;
		// The first turn's id, now committed. Nothing to open: it is already here.
		if (chatId === threadId) {
			openedFor.current = chatId;
			return;
		}
		openedFor.current = chatId;

		stopPlayback();
		setGame(null);
		// Cleared, not carried: the restore effect fetches the new thread's own card.
		setEligibility(null);

		/**
		 * Before the cache, and that ordering is the whole trick: the landing
		 * page wrote this question into the cache to give the rail its row, so
		 * restoring from there first would put the message on screen and then
		 * `resumeFirstTurn` would append it a second time.
		 */
		const pending = takePendingTurn(chatId);
		if (pending) {
			firstTurn.current = pending;
			setArmed((n) => n + 1);
			return;
		}

		// Read from the cache first, and that is not an optimisation.
		const cached = readConversation(queryClient, chatId);
		if (cached && cached.messages.length > 0) {
			openPast(cached);
			return;
		}

		/**
		 * A guide card opens an empty conversation on purpose. It has no rows to
		 * restore and the server has never been told it exists, so the read below
		 * would 404 and send the reader back to the landing -- which is where they
		 * just came from. Nothing to fetch, and that is the correct outcome:
		 * an empty thread is exactly what the welcome renders for.
		 */
		if (isFreshThread(chatId)) {
			// Nothing to fetch -- but the conversation still has to be adopted, or
			// `send` refuses every later turn on the grounds that no conversation
			// is open. That refusal is silent, so the symptom is a composer that
			// takes the reader's question and does nothing with it.
			adoptThread(chatId);
			return;
		}

		/**
		 * An identity first, because a conversation is only readable as its
		 * owner. Then the service directly rather than through Query: this is
		 * the one read whose *failure* has to be acted on, and a rejection is
		 * the only thing that tells an unknown address apart from an empty one.
		 * The result is written back to the cache so the rail and every later
		 * read see it, exactly as the query would have left it.
		 */
		void ensureSession()
			.then((identity) => {
				if (!identity)
					throw new Error("no session to read a conversation with");
				return fetchConversation(chatId);
			})
			.then((stored) => {
				// The reader moved on while this was in flight.
				if (openedFor.current !== chatId) return;
				upsertConversation(queryClient, stored);
				openPast(stored);
			})
			.catch(() => {
				// An address this account has no conversation for: another device, a cleared identity.
				if (openedFor.current !== chatId) return;
				void navigate({
					to: "/",
					search: (previous: AnswerSearch) => previous,
					replace: true,
				});
			});
	}, [
		chatId,
		threadId,
		navigate,
		openPast,
		stopPlayback,
		queryClient,
		adoptThread,
	]);

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

	const startNewChat = useCallback(() => {
		stopPlayback();
		setDrawerOpen(false);
		void navigate({
			to: "/",
			search: (previous: AnswerSearch) => previous,
			viewTransition: true,
		});
	}, [navigate, stopPlayback]);

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

	/** What the open conversation is called. */
	// biome-ignore lint/correctness/useExhaustiveDependencies: activeStoredTitle is the trigger
	const activeTitle = useMemo(() => {
		const stored = threadId
			? readConversation(queryClient, threadId)
			: undefined;
		if (stored) return displayTitle(stored);

		// Nothing stored yet: the first answer is still arriving, so there is no record.
		const firstQuestion = messages.find((m) => m.role === "user");
		return firstQuestion?.role === "user" ? titleFor(firstQuestion.text) : "";
	}, [threadId, activeStoredTitle, messages]);

	// Browser tabs and history entries should say which chat this is.
	useEffect(() => {
		if (typeof document === "undefined") return;
		document.title = activeTitle
			? `${activeTitle} · ASPIRE AI`
			: DEFAULT_DOCUMENT_TITLE;
		// Set by hand, so it has to be put back by hand — leaving here for the
		// landing screen, or for `/signin`, must not keep this chat's name.
		return () => {
			document.title = DEFAULT_DOCUMENT_TITLE;
		};
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
			// Nothing is left to read here, so the landing screen is where this lands.
			void navigate({
				to: "/",
				search: (previous: AnswerSearch) => previous,
				replace: true,
				viewTransition: true,
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
		/* The interface's own age band, which until now ran on the internal
		   widget-preview route and nowhere else — so every reader, teachers
		   included, got the five-year-old's configuration by fallback. Derived
		   from the guide they chose; see `bandForPersona`. */
		<AgeBandProvider
			// ORDER MATTERS, and it was wrong. `identity.ageBand` came second, but
			// for an ANONYMOUS session `/api/auth/anonymous` returns the youngest
			// band for everyone -- it describes the account, which has no persona,
			// and 5-8 is the safe answer there. So a signed-out reader who picked
			// Zion, Imani or Azuri got `data-band="5-8"` and `bandForPersona`,
			// which returns 13-15 for orion, was never reached.
			//
			// A SIGNED-IN reader is different: their band comes from their date of
			// birth and is the real answer, so it still beats the guide they
			// picked. Hence the account-type check rather than a plain reorder.
			band={
				band ??
				(identity?.accountType === "registered" ? identity.ageBand : null) ??
				bandForPersona(persona) ??
				identity?.ageBand
			}
		>
			<div
				className="app"
				data-phase="chat"
				/* The orb's colour, and nothing else, reads this. One attribute at
				   the root beats drilling the persona through the transcript to
				   reach a decorative sphere. Falls back to `guest`, which is the
				   voice that answers before it knows who is reading. */
				data-persona={persona || "guest"}
				data-band={band ?? identity?.ageBand ?? undefined}
				data-rail={railClosed ? "collapsed" : "expanded"}
			>
				<div className="atmosphere" aria-hidden="true">
					<span />
					<span />
					<span />
					<span />
				</div>

				{/* First visit only — someone who arrived on a shared link rather than
			    through the landing page. The chooser is not put here: this reader
			    is already mid-conversation, and the composer's persona control is
			    the right way to change guide from inside one. */}
				<FirstRun />

				<div className="frame">
					<Rail
						collapsed={railClosed}
						unreachable={compact && !drawerOpen}
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
						persona={persona}
						band={band}
						onPersonaChange={setPersona}
						onSeed={ask}
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

						{/* EN / ES / FR. Its own corner slot rather than a fourth control
						    beside the guide picker; see `LanguageSwitcher`. */}
						<div
							className="lang-slot"
							data-with-account={railClosed || undefined}
						>
							<LanguageSwitcher
								selected={voice.language as HookLanguage}
								onChoose={(next) => voice.setLanguage(next)}
							/>
						</div>

						{/* The way into an account, whenever the sidebar is not there to carry it. */}
						{/* `inert` as well as the CSS, because they cover different people. */}
						<div
							className="account-slot"
							data-shown={railClosed || undefined}
							inert={!railClosed || undefined}
						>
							<AccountControl variant="corner" />
						</div>

						{/* Above the transcript, not after it: each answer carries its own
					    `h2`, and a page whose first heading is an `h2` reads to a
					    screen reader as a document that starts mid-outline. */}
						<h1 className="sr-only">Conversation with {guideName}</h1>

						<ChatTitleBar
							title={activeTitle}
							showDrawerTrigger={compact}
							drawerOpen={drawerOpen}
							onOpenRail={openDrawer}
							onRename={(title) => {
								if (threadId) renameChat(threadId, title);
							}}
						/>

						<div className="stage">
							<div
								className="thread"
								ref={threadRef}
								// Banked on every scroll: a chat can also be left by the back button or a shortcut.
								onScroll={(event) => {
									// Not during a restore: that scroll is ours, and banking it overwrites the saved offset.
									if (restoring.current) return;
									scrollTops.current.set(
										scrollKey,
										event.currentTarget.scrollTop,
									);
								}}
							>
								<div className="thread__inner">
									{/* THE HOOK ALWAYS, THE CHIPS ONLY WHEN THE THREAD IS EMPTY.
									    This used to be one condition for both, which meant a
									    reader who chose a guide and typed a question on the
									    landing never saw that guide greet them: staging the
									    turn made the thread non-empty before the chat first
									    painted. The greeting is beats one to three of the
									    spine and belongs at the top of the conversation
									    either way; it scrolls off as the conversation grows. */}
									<ChatWelcome
										showCards={
											messages.length === 0 && !streaming && !isThinking
										}
										persona={persona}
										language={voice.language as HookLanguage}
										priorConversations={priorConversations}
										onAsk={ask}
									/>
									<section aria-label="Conversation">
										<Transcript
											guideName={guideName}
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
											gameSound={voice.gameSound}
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
																// Card closed: report the score once, on the game-result channel.
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
									<VoiceConsent
										onAllow={voice.allowMic}
										onDeny={voice.denyMic}
									/>
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
								onSend={ask}
								busy={!settled}
								onStop={handleStop}
								simpleMode={simpleMode}
								onToggleSimpleMode={toggleSimpleMode}
								persona={persona}
								band={band}
								onPersonaChange={setPersona}
								draft={draft}
								onDraftChange={setDraft}
								focusSignal={0}
								voice={voice}
							/>
						</div>

						{/* `<output>` carries `role="status"` implicitly, with less markup.
					    `aria-atomic`, so a changed tail is not read on its own. */}
						<output className="sr-only" aria-live="polite" aria-atomic="true">
							{announcement}
						</output>

						{/* One text node: as two, the flex gap made "can" and "make" run together when copied. */}
						<p className="disclaimer">ASPIRE AI can make mistakes.</p>
					</main>
				</div>
			</div>
		</AgeBandProvider>
	);
}
