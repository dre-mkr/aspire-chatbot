import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef } from "react";
import {
	claimConversations,
	deleteConversation,
	HttpError,
	renameConversation,
} from "./conversations";
import { forgetLocalConversation, loadConversations } from "./history";
import { answerToText } from "./knowledge";
import {
	clearTitleLockInCache,
	conversationQuery,
	conversationsQuery,
	keys,
	removeConversationFromCache,
	retitleInCache,
	titleSnapshot,
	upsertConversation,
} from "./queries";
import { ensureSession } from "./session";
import { requestTitle } from "./title";
import { useSession } from "./use-session";

/**
 * Threads this browser has already tried to name. Module-level, not a ref:
 * this hook unmounts on every move between the landing and a chat, and a
 * per-mount Set would forget a title you had just set by hand.
 */
const titledThreads = new Set<string>();

/** The stranded-conversation sweep below belongs to the page load, not the mount. */
let adopted = false;

export interface UseConversationListOptions {
	/** Which conversation is open, so its stored name can be watched. */
	activeThreadId?: string | null;
	/** Which language to name conversations in. */
	getLanguage?: () => string;
}

/**
 * The rail's data and its row actions, held apart from the chat engine.
 *
 * Both pages drive the same sidebar, but only one of them has a conversation
 * open, so the list and its mutations cannot live inside `useConversation`.
 * That hook calls this one, which keeps a single owner for `titledThreads`.
 */
export function useConversationList({
	activeThreadId = null,
	getLanguage = () => "en",
}: UseConversationListOptions = {}) {
	const queryClient = useQueryClient();

	// Subscribed to the session: a sign-in or sign-out re-renders and requeries the new owner.
	const { session } = useSession();
	const ownerId = session?.userId ?? "anon";

	// Drives the layout: whether there is anything for the rail to offer at all.
	const { data: hasHistory = false } = useQuery({
		...conversationsQuery(ownerId),
		select: (rows) => rows.length > 0,
	});
	/** The open conversation's stored name, as the title bar's change trigger. */
	const { data: activeStoredTitle } = useQuery({
		...conversationsQuery(ownerId),
		select: (rows) =>
			rows.find((row) => row.threadId === activeThreadId)?.title,
	});

	/**
	 * Adopt the conversations this browser started before ownership existed.
	 * It lives with the list rather than with the chat engine: the rail is on
	 * both pages, so a visitor who never opens a chat must still get their
	 * history back.
	 */
	// biome-ignore lint/correctness/useExhaustiveDependencies: once, on mount
	useEffect(() => {
		if (adopted) return;
		adopted = true;

		// An identity first, because everything user-scoped is gated on having one.
		void ensureSession()
			.then(async (identity) => {
				if (!identity) return;
				// The queries were disabled while there was no session.
				await queryClient.invalidateQueries({
					queryKey: conversationsQuery().queryKey,
				});

				const stranded = loadConversations().map((c) => c.threadId);
				if (stranded.length === 0) return;
				const claimed = await claimConversations(stranded).catch(() => 0);
				if (claimed > 0) {
					await queryClient.invalidateQueries({
						queryKey: conversationsQuery().queryKey,
					});
				}
			})
			.catch(() => undefined);
	}, []);

	// Held in a ref: the voice layer that answers this is built after the hook.
	const getLanguageRef = useRef(getLanguage);
	useEffect(() => {
		getLanguageRef.current = getLanguage;
	}, [getLanguage]);

	const markTitled = useCallback((id: string) => {
		titledThreads.add(id);
	}, []);
	const hasTitled = useCallback((id: string) => titledThreads.has(id), []);

	/** Names a conversation, in the cache and on the server. */
	const renameMutation = useMutation({
		mutationFn: ({
			id,
			title,
			source,
		}: {
			id: string;
			title: string;
			source: "generated" | "manual";
		}) => renameConversation(id, title, source),
		onMutate: ({ id, title, source }) => {
			const previous = titleSnapshot(queryClient, id);
			retitleInCache(queryClient, id, title, source);
			return { id, previous };
		},
		onError: (_error, _variables, context) => {
			if (!context) return;
			retitleInCache(
				queryClient,
				context.id,
				context.previous.title,
				context.previous.titleSource,
			);
		},
		// Runs on success and on failure alike.
		onSettled: () =>
			queryClient.invalidateQueries({ queryKey: keys.allConversations() }),
	});

	// Deliberately fire-and-forget: a name that fails to save is not worth interrupting for.
	const nameConversation = useCallback(
		(id: string, title: string, source: "generated" | "manual") => {
			renameMutation.mutate({ id, title, source });
		},
		[renameMutation.mutate],
	);

	/** Deletes a conversation, for good. */
	const deleteMutation = useMutation({
		mutationFn: (id: string) => deleteConversation(id),
		onMutate: (id: string) => ({
			removed: removeConversationFromCache(queryClient, id),
		}),
		onSuccess: (_result, id) => {
			// The device-local copy still holds transcripts from before history moved server-side.
			forgetLocalConversation(id);
		},
		onError: (error, _id, context) => {
			if (error instanceof HttpError && error.status === 404) return;
			if (context?.removed) upsertConversation(queryClient, context.removed);
		},
		// Ordering after a rollback comes from this refetch: the restore puts the row on top.
		onSettled: () =>
			queryClient.invalidateQueries({ queryKey: keys.allConversations() }),
	});

	/** Deletes one conversation. */
	const deleteChat = useCallback(
		(id: string) => {
			deleteMutation.mutate(id);
		},
		[deleteMutation.mutate],
	);

	/** Renames a conversation by hand. */
	const renameChat = useCallback(
		(id: string, title: string) => {
			titledThreads.add(id);
			nameConversation(id, title, "manual");
		},
		[nameConversation],
	);

	/** Asks for a fresh title for one conversation. */
	const regenerateTitle = useCallback(
		(id: string) => {
			// The rail's rows carry no transcripts, so the opening exchange is fetched.
			void queryClient
				.ensureQueryData(conversationQuery(id))
				.then((stored) => {
					const question = stored.messages.find((m) => m.role === "user");
					const answer = stored.messages.find((m) => m.role === "assistant");
					if (question?.role !== "user" || answer?.role !== "assistant") return;

					clearTitleLockInCache(queryClient, id);
					titledThreads.add(id);

					return requestTitle({
						message: question.text,
						answer: answerToText(answer.blocks),
						language: getLanguageRef.current(),
					}).then((title) => {
						if (!title) return;
						nameConversation(id, title, "generated");
					});
				})
				.catch(() => undefined);
		},
		[queryClient, nameConversation],
	);

	return {
		hasHistory,
		activeStoredTitle,
		nameConversation,
		markTitled,
		hasTitled,
		renameChat,
		regenerateTitle,
		deleteChat,
	};
}
