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
import { MenuIcon } from "#/components/icons";
import {
	clearEligibilityResult,
	type EligibilityState,
	loadEligibilityResult,
} from "#/lib/aspire/eligibility";
import { downloadTranscript } from "#/lib/aspire/export";
import type { GamePersona, GameState } from "#/lib/aspire/games";
import {
	displayTitle,
	type StoredConversation,
	titleFor,
} from "#/lib/aspire/history";
import { answerToText, starterPrompts } from "#/lib/aspire/knowledge";
import {
	conversationQuery,
	eligibilityStateQuery,
	gameStateQuery,
	invalidateAfterTurn,
	readConversation,
} from "#/lib/aspire/queries";
import { useConversation } from "#/lib/aspire/use-conversation";
import { useVoice } from "#/lib/aspire/use-voice";
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
/**
 * The playback id the eligibility card speaks under.
 *
 * Negative so it can never collide with a message id, which are minted from
 * zero upwards. Playback is keyed by id so that pressing the speaker twice
 * pauses rather than restarts, and the card needs one that is not a turn.
 */
const ELIGIBILITY_SPEECH_ID = -1;

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

	const navigate = useNavigate();
	const queryClient = useQueryClient();
	/**
	 * Which conversation the URL is pointing at, or undefined at `/`.
	 *
	 * Derived from the committed pathname rather than from `useParams`, and that
	 * is not a stylistic choice. Read as a param, `chatId` goes
	 * undefined → minted → undefined → minted across a single navigation, because
	 * for one render the new match is resolving and the old one is gone. The
	 * reconciler below reads "no chat id" as "the user is at the empty state" and
	 * resets — so a conversation was being wiped and then restored from the
	 * half-written storage record one tick after it was sent, which replaced the
	 * answer that was streaming in with the never-got-an-answer recovery turn.
	 *
	 * One atomic string cannot have that gap: the location is either `/` or a
	 * chat, and it changes exactly once per navigation.
	 */
	const pathname = useRouterState({ select: (s) => s.location.pathname });
	const chatId = pathname.startsWith(CHAT_PREFIX)
		? decodeURIComponent(pathname.slice(CHAT_PREFIX.length))
		: undefined;

	/**
	 * A chat that has been minted and navigated to, but whose URL has not landed.
	 *
	 * `send` mints an id and asks for the navigation synchronously; the router
	 * commits it a tick later. In that gap `chatId` is still undefined while a
	 * live conversation exists, and the reconciler below would read that as "the
	 * user is at the empty state" and reset the chat that was just started. This
	 * holds the gap open until the address catches up.
	 */
	const awaitingUrl = useRef<string | null>(null);
	/** One press of "New chat" is one navigation, however fast it is repeated. */
	const startingNew = useRef(false);
	/**
	 * The language each eligibility check opened in, by thread.
	 *
	 * A check opens in a language and finishes in it — that is the rule the
	 * eligibility key is shaped around. Holding the language here is what makes
	 * the rule true rather than merely stated: the query function is handed this
	 * captured value instead of reading the live one, so a refetch under the
	 * unchanged key cannot switch the card's language part-way through.
	 *
	 * A ref, not state: it is read during render but changing it must never
	 * itself cause one, and every path that sets it is already re-rendering.
	 */
	const checkLanguage = useRef(new Map<string, string>());

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
		regenerate,
		stop,
		openPast,
		reset,
		renameChat,
		regenerateTitle,
	} = useConversation({
		onAnswer: (id, text) => speakArrival.current(id, text),
		persona,
		// Titles are written in the language the interface is set to, read from
		// the existing voice setting rather than detected separately. A getter
		// because `voice` is constructed below — it needs the thread id this
		// hook returns.
		getLanguage: () => voice.language,
		// The first message of a chat gives it an address. `replace`, not push:
		// `/` and `/chat/:id` are the same conversation at two ages, not two
		// places, so Back from a chat you just started belongs to whatever you
		// were doing before it — not to a stale empty version of itself.
		// A game turn carries no text, so the card is the whole of it. Fetched
		// rather than taken from the chat response because the games endpoint is
		// the one authority on session state -- the same state a refresh restores
		// from, so the card is identical whether it just appeared or was reloaded.
		onGameStart: (id) => {
			setGame(null);
			// Through the cache rather than around it, so the query above finds
			// this rather than asking again a moment later.
			//
			// `staleTime: 0` overrides the query's own infinite staleness for this
			// one read, and it is load-bearing: the cache may well hold a null from
			// before this game existed, and "never stale" would hand that back and
			// the card would never appear.
			void queryClient
				.fetchQuery({ ...gameStateQuery(id), staleTime: 0 })
				.then((state) => {
					if (state) setGame(state);
				})
				.catch(() => undefined);
		},
		// The card carries the whole turn, so it is fetched rather than taken
		// from the chat response: the eligibility endpoint is the one authority
		// on the flow's state, and it is the same state a refresh restores from.
		// A new check replaces any stored result for this thread — the old
		// verdict answered a question that is being asked again.
		onEligibilityStart: (id, language) => {
			clearEligibilityResult(id);
			setEligibility(null);
			// The language the check opened in, captured here and not read again.
			// See `checkLanguage` below.
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
				// Carried, not dropped. A navigation without this resets the
				// search to the route's default, so asking the first question of a
				// chat in plain-words mode would have silently turned it off at the
				// exact moment the answer was being composed.
				search: (previous: ShellSearch) => previous,
				replace: true,
			});
		},
	});

	const compact = useMediaQuery(COMPACT);
	const [railCollapsed, setRailCollapsed] = useState(false);
	const [drawerOpen, setDrawerOpen] = useState(false);

	/**
	 * The plain-words toggle, read from the address rather than from state.
	 *
	 * It changes what the assistant is asked to produce, which makes it part of
	 * the question and not part of the session — so it belongs somewhere it can
	 * be linked to and handed on. `replace` on the way in because toggling it is
	 * an adjustment to the current view, not a place: it never added a history
	 * entry when it lived in `useState`, and it must not start now.
	 */
	const { simple } = useSearch({ from: "/_shell" });
	const simpleMode = simple === true;
	const toggleSimpleMode = useCallback(() => {
		void navigate({
			to: ".",
			search: (previous: ShellSearch): ShellSearch =>
				previous.simple ? {} : { simple: true },
			replace: true,
		});
	}, [navigate]);
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
	/**
	 * The eligibility card's state.
	 *
	 * Comes from the server while the flow is running, and from device storage
	 * once it has finished — the server deletes the session in the same call
	 * that produces the result, so there is nothing left to fetch. That is the
	 * design, not a gap: a minor's answers were always meant to stay on this
	 * device, and the result is derived from them.
	 */
	const [eligibility, setEligibility] = useState<EligibilityState | null>(null);
	const settled = !isThinking && !streaming;

	/**
	 * The server's answer for this thread's game, cached by Query.
	 *
	 * Query owns the fetching. It does not own what is on screen: `game` above
	 * is the card being displayed, and the two are deliberately not the same
	 * thing. A finished game has no session left on the server, so this query
	 * correctly goes null — but the card is still showing a child what they just
	 * learned, and it closes on their say-so, not on a cache transition.
	 */
	const gameQuery = useQuery(gameStateQuery(threadId, settled));

	// Adopt, never clear. This is the whole of the rule above, and it is why the
	// effect reads the query rather than the query driving the render.
	useEffect(() => {
		if (gameQuery.data) setGame(gameQuery.data);
	}, [gameQuery.data]);

	/**
	 * Restores the eligibility card, from whichever half still holds it.
	 *
	 * Two sources, and which one applies says where the flow got to:
	 *
	 * - The server, while questions are still being answered. This is what makes
	 *   a refresh mid-flow a non-event.
	 * - Device storage, once a verdict exists. The server deleted the session
	 *   the moment it produced the result, so this is the only copy — and it is
	 *   the copy that should exist, since the answers behind it were never
	 *   supposed to leave this device.
	 *
	 * The server is asked first because a running flow outranks a stored result
	 * from a check that was restarted.
	 */
	const eligibilityQuery = useQuery(
		// The captured language, not the live one.
		//
		// The key is deliberately not language-scoped — switching the interface
		// language part-way through a check must not refetch and redraw the card
		// being answered. But the query function used to close over the live
		// `voice.language`, so any refetch under that unchanged key re-ran the
		// request in whatever language was current and wrote it back to the same
		// entry: the card changed language mid-check, which is exactly what the
		// key's comment says must not happen.
		//
		// `checkLanguage` holds what the flow opened in. The fallback is only
		// reached when a check is restored after a reload, where nothing captured
		// it and the current language is the best available answer.
		eligibilityStateQuery(
			threadId,
			(threadId ? checkLanguage.current.get(threadId) : undefined) ??
				voice.language,
			settled,
		),
	);

	/**
	 * The completion handoff.
	 *
	 * The streaming layer knows when a turn is over; Query knows what that could
	 * have changed. This effect is the entire contract between them, and it fires
	 * on the transition into settled rather than on `settled` being true — a
	 * re-render while already settled must not re-ask the server.
	 *
	 * Watching the transition covers every way a turn can end: the reveal
	 * finishing, the reader stopping it part-way, a failure, and the two turns
	 * that are a card and nothing else. Hanging it off `finishStream` alone would
	 * have covered only the first.
	 *
	 * This replaces the `settled` dependency the two fetch effects used to carry.
	 * The trigger is unchanged; what changed is that it is now stated once, in
	 * terms of what became invalid, instead of twice in terms of what to refetch.
	 */
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

		// Server says no session. That means either the check finished — in which
		// case the verdict is on this device and nowhere else — or there never was
		// one, in which case there is nothing to show and the card stays absent.
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

	// The rail is a drawer whenever it has nowhere to sit as a column: on a
	// narrow screen, and on the landing screen at any width, where `--rail-w` is
	// 0 so the gradient can run full-bleed.
	//
	// It used to be simply unreachable on landing, which made a refresh a dead
	// end: `phase` resets to `landing`, so a returning user saw the hero with no
	// route to the conversations the rail advertises are saved on this device —
	// and on a phone no control rendered at all until they asked something new.
	const drawerMode = compact || phase === "landing";
	const railClosed = drawerMode ? !drawerOpen : railCollapsed;
	const drawerModal = drawerMode && drawerOpen;

	// Announce discrete events, not the stream. A live region around the
	// transcript itself would read every four-word tick out loud.
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

	/**
	 * Where each conversation was left, keyed by thread.
	 *
	 * Deliberately a ref and deliberately not persisted: it should survive
	 * switching between chats in one sitting, which is when losing your place is
	 * infuriating, and it should not survive a reload, where restoring someone
	 * to the middle of a transcript they have not seen this session is worse
	 * than showing them the end of it.
	 */
	const scrollTops = useRef(new Map<string, number>());
	/**
	 * True while the restore below is assigning an offset.
	 *
	 * Assigning `scrollTop` fires `scroll`, and the handler that banks positions
	 * cannot tell that event apart from a person scrolling. Without this, a
	 * restore that the browser clamps banks the clamped value over the one being
	 * restored, and the remembered position is lost by the act of restoring it.
	 */
	const restoring = useRef(false);
	/** `""` is the new chat, which has no id and cannot collide with one. */
	const scrollKey = threadId ?? "";

	/** Which thread the follow-the-stream effect is currently chasing. */
	const following = useRef<string | null>(null);

	// Follow the answer as it streams, but only while the reader is already at
	// the bottom — scrolling up to re-read something should not get yanked back.
	// `streaming` is the trigger rather than an input: every revealed word grows
	// the thread and has to be chased. Dropping it freezes the scroll mid-answer.
	// biome-ignore lint/correctness/useExhaustiveDependencies: change trigger
	useEffect(() => {
		const thread = threadRef.current;
		if (!thread || phase !== "chat") return;

		// A different conversation just arrived. Its messages changed, but they
		// did not *stream* in — they were read out of storage, and the effect
		// below has already put the reader back where they left off. Chasing the
		// bottom here would undo that on every chat switch.
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

	// Restore before paint, so a reopened conversation is never briefly shown at
	// the wrong offset. A thread with no remembered position — anything opened
	// for the first time this session — starts at its newest message.
	//
	// Only ever for a real conversation. Running this on the empty state scrolled
	// the landing thread to its end, which carries the hero up over the lightest,
	// most magenta band of the gradient — and that is measurably the wrong place
	// for it to be: `.hero__sub` dropped from 5.68:1 to 3.67:1 at 1280, back
	// under AA and back into a defect this review had already fixed once.
	//
	// Runs on `messages` as well as `threadId`, and that is the whole fix. On
	// `threadId` alone it fired while the PREVIOUS conversation's transcript was
	// still in the DOM, so a remembered 399px was assigned to a container that
	// was still only as tall as the chat being left — the browser clamped it,
	// usually to 0, and the taller content then arrived under an offset nobody
	// asked for. Worse, the clamp fires `scroll`, which banked that 0 over the
	// position being restored: the offset was not merely ignored, it was
	// destroyed on the way in. Measured at one restore in five surviving.
	//
	// `restoredFor` makes it once-per-conversation rather than once-per-render,
	// so later turns in an open chat do not drag the reader anywhere.
	const restoredFor = useRef<string | null>(null);
	useLayoutEffect(() => {
		const thread = threadRef.current;
		if (!thread || !threadId) return;
		if (restoredFor.current === threadId) return;
		// Nothing to measure against yet; wait for the transcript to render.
		if (messages.length === 0) return;

		restoredFor.current = threadId;
		const saved = scrollTops.current.get(threadId);
		// Suppress the `scroll` this assignment provokes, so restoring a position
		// cannot overwrite the position being restored.
		restoring.current = true;
		thread.scrollTop = saved ?? thread.scrollHeight;
		requestAnimationFrame(() => {
			restoring.current = false;
		});
	}, [threadId, messages]);

	/**
	 * One unsent draft per conversation.
	 *
	 * Typing half a question, going to check something in another chat, and
	 * coming back to find the box empty is a small theft that both reference
	 * products avoid. The draft belongs to the conversation, not to the app.
	 */
	const drafts = useRef(new Map<string, string>());
	const draftKey = useRef("");
	const liveDraft = useRef(draft);

	// Declared before the swap below so that, on the commit where the thread
	// changes, the value being banked is the one that was actually in the box.
	useEffect(() => {
		liveDraft.current = draft;
	}, [draft]);

	useEffect(() => {
		if (scrollKey === draftKey.current) return;
		drafts.current.set(draftKey.current, liveDraft.current);
		draftKey.current = scrollKey;
		setDraft(drafts.current.get(scrollKey) ?? "");
	}, [scrollKey]);

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
		if (drawerMode) setDrawerOpen((open) => !open);
		else setRailCollapsed((collapsed) => !collapsed);
	}, [drawerMode]);

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

	/**
	 * Bumped whenever the composer should take the cursor.
	 *
	 * Starts at 1 rather than 0 so the initial render already counts as a
	 * request: landing on the empty state puts you in the box with nothing to
	 * click.
	 */
	const [focusSignal, setFocusSignal] = useState(1);
	const focusComposer = useCallback(() => setFocusSignal((n) => n + 1), []);

	/**
	 * Makes the conversation match the URL, in one direction only.
	 *
	 * The address is the single source of truth for which chat is open, so every
	 * way of changing chats — a sidebar row, "New chat", the back button, a
	 * pasted link, a refresh — is one navigation and this one reconciler, rather
	 * than each entry point doing its own loading and hoping they agree.
	 */
	useEffect(() => {
		// A chat has been started but the router has not committed its URL yet.
		// Doing anything here would act on an address that is one tick stale.
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

		// Read from the cache first, and that is not an optimisation. Switching
		// chats used to be synchronous because history was localStorage, and the
		// route loader keeps it that way by having the transcript in hand before
		// the navigation commits. Only a link opened cold falls through to the
		// fetch below.
		const cached = readConversation(queryClient, chatId);
		if (cached && cached.messages.length > 0) {
			stopPlayback();
			setGame(null);
			// Cleared rather than carried across: the restore effect above reads
			// the new thread's own card, and showing the previous conversation's
			// verdict for a frame would be showing it to the wrong person.
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
				// An address for a conversation this account does not have: a link
				// from another device, a cleared identity, a hand-typed id. The
				// honest answer is the empty state, and `replace` so Back does not
				// walk into the same dead id again.
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
				// The setting belongs to the reader, not to the conversation, so it
				// survives moving between them — exactly as it did as component state.
				search: (previous: ShellSearch) => previous,
			});
		},
		[navigate],
	);

	const startNewChat = useCallback(() => {
		// Already on an empty new chat: this is a no-op with a cursor. No second
		// navigation, no second history entry, and above all no clearing of a
		// draft someone is part-way through typing — pressing "New chat" when you
		// are already in a new chat should never cost you a sentence.
		if (!chatId && messages.length === 0) {
			setDrawerOpen(false);
			focusComposer();
			return;
		}
		if (startingNew.current) return;
		startingNew.current = true;

		// A deliberate move to the empty state outranks a first send that is
		// still settling, so the gap-holder is dropped rather than left to skip
		// the reconciler forever.
		awaitingUrl.current = null;
		stopPlayback();
		setDrawerOpen(false);
		void navigate({ to: "/", search: (previous: ShellSearch) => previous });
		focusComposer();
	}, [chatId, messages.length, focusComposer, navigate, stopPlayback]);

	/**
	 * Cmd/Ctrl+Shift+O — the same binding both reference products use.
	 *
	 * Checked against everything already bound here before taking it: the only
	 * other window-level listeners are three Escape handlers (the drawer, the
	 * row menu, the voice sheet), and the games card's T/F keys are scoped to
	 * the card and already ignore modifiers. Nothing collides.
	 *
	 * `event.code` rather than `event.key`, because with Shift held the
	 * character a layout produces is not reliably "O".
	 */
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

	/**
	 * Writes out one conversation from the rail.
	 *
	 * Prefers the live transcript when the row is the open thread, because that
	 * one can be a turn ahead of storage — a conversation is persisted once its
	 * answer settles, so an answer still revealing is not in there yet.
	 * Otherwise the stored copy is the whole of it.
	 */
	/**
	 * What the open conversation is called.
	 *
	 * Read from the same stored record the rail reads, so the bar and the list
	 * can never disagree about a chat's name.
	 *
	 * `activeStoredTitle` is the dependency and it is a trigger, not an input:
	 * the value below comes from `readConversation`, which prefers a loaded
	 * transcript over the list summary, but it needs a reason to re-run when a
	 * rename lands. That reason used to be a subscription to the entire
	 * conversation list, which re-rendered this whole surface whenever any row
	 * moved. It is now one string, selected out of the same query.
	 */
	// biome-ignore lint/correctness/useExhaustiveDependencies: activeStoredTitle is the trigger
	const activeTitle = useMemo(() => {
		const stored = threadId
			? readConversation(queryClient, threadId)
			: undefined;
		if (stored) return displayTitle(stored);

		// Nothing is stored yet -- the first answer is still arriving, so there is
		// no thread id and no record. Falling through to "" left the bar blank
		// for the whole of the first reply, with an 8px-tall invisible rename
		// button stretched across it. The question just asked is the right thing
		// to show, and it is the same string the fallback ladder would land on.
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

	const handleSaveConversation = useCallback(
		(conversation: StoredConversation) => {
			const live = conversation.threadId === threadId && messages.length > 0;
			downloadTranscript(live ? messages : conversation.messages);
		},
		[messages, threadId],
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
					{/* The top bar is gone. Its three pieces moved: voice settings to
					    the composer, Save chat to each conversation's row in the rail,
					    and the identity line into the empty state.

					    This control did not move, because it was never the bar's — it
					    is the only way to open the rail whenever the rail is a drawer,
					    and on the landing screen it is the only route to conversations
					    saved on this device. Deleting the bar around it would have put
					    that dead end back. It floats over the thread instead. */}
					{/* Only on the landing screen, where there is no bar to hold it.
					    In the chat phase the bar carries it, so it is never
					    duplicated. */}
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

					{/* The way into an account, whenever the sidebar is not there to
					    carry it. Keyed on the sidebar rather than on the route: a
					    conversation with the rail collapsed needs this just as much
					    as the landing screen does, and the landing screen with the
					    drawer open does not.

					    Both this and the sidebar block stay mounted; which one is
					    visible is a matter of opacity, so the handover during the
					    560ms morph is a cross-fade rather than one popping out as
					    the other pops in. */}
					{/* `inert` as well as the CSS, because they cover different people.
					    The slot fades out with `opacity: 0; pointer-events: none`, which
					    stops a pointer and does nothing about a keyboard: the sign-in
					    button stayed in the tab order while invisible, so tabbing across
					    the chat screen landed focus on a control nobody could see. */}
				<div
						className="account-slot"
						data-shown={railClosed || undefined}
						inert={!railClosed || undefined}
					>
						<AccountControl variant="corner" />
					</div>

					{/* No bar on the empty state: the hero already carries the
					    product's identity, and a bar saying "New chat" above it would
					    be chrome announcing nothing. */}
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
							// Banked continuously rather than on the way out: a chat can
							// also be left by the back button or a keyboard shortcut, and
							// there is no single exit to hook.
							onScroll={(event) => {
								// Not while a restore is mid-assignment: that event is this
								// component's own, and banking it overwrites the position it
								// is in the middle of putting back.
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
									{/* Identity and regional grounding, worth most on first
									    contact and worth nothing on the fortieth turn — so it
									    lives in the empty state and goes away once you start.
									    Deleted by a60512e, a commit about removing an unreachable
									    voice scale; its stylesheet rule, that rule's measured
									    contrast note, and `topbar-move.mjs` all survived and went
									    on describing an element that was no longer rendered. */}
									<p className="hero__identity">
										Financial literacy assistant · St. Kitts and Nevis
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
										game={
											game && threadId
												? {
														threadId,
														state: game,
														onChanged: setGame,
													}
												: null
										}
										eligibility={
											eligibility && threadId
												? {
														threadId,
														state: eligibility,
														onChanged: setEligibility,
														// Speaks the question, or the verdict. Never
														// the option labels: read aloud, a list of
														// things to choose between becomes a wall of
														// speech that has to be held in memory to be
														// any use.
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

						<Composer
							onSend={ask}
							busy={!settled}
							onStop={handleStop}
							simpleMode={simpleMode}
							onToggleSimpleMode={toggleSimpleMode}
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

					{/* The hero h1 goes inert with the hero, so the conversation
					    supplies the page heading once it takes over. */}
					{phase === "chat" ? (
						<h1 className="sr-only">Conversation with ASPIRE AI</h1>
					) : null}

					<output className="sr-only">{announcement}</output>

					<p className="disclaimer">
						ASPIRE AI can
						<strong>make mistakes</strong>
					</p>
				</main>
			</div>
		</div>
	);
}
