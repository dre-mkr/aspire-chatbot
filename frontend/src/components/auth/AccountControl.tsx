import { useQueryClient } from "@tanstack/react-query";
import { useNavigate, useRouterState } from "@tanstack/react-router";
import { useEffect, useId, useRef, useState } from "react";
import { signOut } from "#/lib/aspire/auth";
import { keys } from "#/lib/aspire/queries";
import { useSession } from "#/lib/aspire/use-session";
import { Avatar } from "./Avatar";

/** The way in and out of an account, in both of the places it appears. */

interface AccountControlProps {
	/** "corner" floats over the page; "rail" is the block at the sidebar foot. */
	variant: "corner" | "rail";
}

export function AccountControl({ variant }: AccountControlProps) {
	const { session, resolved } = useSession();
	const navigate = useNavigate();
	const queryClient = useQueryClient();
	const pathname = useRouterState({ select: (s) => s.location.pathname });

	const [open, setOpen] = useState(false);
	const [confirming, setConfirming] = useState(false);
	const menuId = useId();
	const wrapper = useRef<HTMLDivElement>(null);
	const trigger = useRef<HTMLButtonElement>(null);

	// Escape closes, and a click outside closes.
	useEffect(() => {
		if (!open) return;
		const onKey = (event: KeyboardEvent) => {
			if (event.key === "Escape") {
				setOpen(false);
				setConfirming(false);
				trigger.current?.focus();
			}
		};
		const onPointer = (event: PointerEvent) => {
			if (!wrapper.current?.contains(event.target as Node)) {
				setOpen(false);
				setConfirming(false);
			}
		};
		window.addEventListener("keydown", onKey);
		window.addEventListener("pointerdown", onPointer);
		return () => {
			window.removeEventListener("keydown", onKey);
			window.removeEventListener("pointerdown", onPointer);
		};
	}, [open]);

	const signedIn = session?.accountType === "registered";

	/** Nothing committal until the session is known. */
	if (!resolved) {
		return (
			<div
				className={
					variant === "corner"
						? "account account--corner"
						: "account account--rail"
				}
			>
				<div className="account__placeholder" aria-hidden="true" />
			</div>
		);
	}

	function goToSignIn() {
		// Carried so that signing in returns you to whatever you were reading rather than to a generic landing screen.
		void navigate({ to: "/signin", search: { next: pathname } });
	}

	async function handleSignOut() {
		setOpen(false);
		setConfirming(false);
		// Handed to `signOut` rather than run here, so the caches are dropped in the moment between the old session bei…
		await signOut(() => {
			queryClient.removeQueries({ queryKey: keys.allConversations() });
			queryClient.removeQueries({ queryKey: keys.allGames() });
			queryClient.removeQueries({ queryKey: keys.allEligibility() });
		});
		void navigate({ to: "/" });
	}

	if (!signedIn) {
		if (variant === "corner") {
			return (
				<div className="account account--corner">
					<button
						type="button"
						className="account__signin"
						onClick={goToSignIn}
					>
						Sign in
					</button>
				</div>
			);
		}
		// The sidebar's signed-out state keeps the shape it has always had: the icon slot, the name line, the note.
		return (
			<div className="account account--rail">
				<button type="button" className="account__block" onClick={goToSignIn}>
					<span className="rail__device" aria-hidden="true">
						<DeviceGlyph />
					</span>
					<span className="rail__identity rail__fold">
						<span className="rail__name">Not signed in</span>
						<span className="rail__note">Sign in to keep your chats</span>
					</span>
				</button>
			</div>
		);
	}

	const name = session?.displayName ?? "Your account";
	const email = session?.email ?? "";

	return (
		<div
			className={
				variant === "corner"
					? "account account--corner"
					: "account account--rail"
			}
			ref={wrapper}
		>
			<button
				type="button"
				ref={trigger}
				className={
					variant === "corner" ? "account__avatar-btn" : "account__block"
				}
				aria-haspopup="menu"
				aria-expanded={open}
				aria-controls={open ? menuId : undefined}
				onClick={() => setOpen((was) => !was)}
			>
				<Avatar
					name={name}
					url={session?.avatarUrl}
					size={variant === "corner" ? 36 : 36}
				/>
				{/* The corner is the avatar and nothing else: a name beside it would compete with the centred hero for attention. */}
				{variant === "rail" ? (
					<span className="rail__identity rail__fold">
						<span className="rail__name">{name}</span>
						<span className="rail__note">{email}</span>
					</span>
				) : null}
			</button>

			{open ? (
				<div
					className="account__menu"
					id={menuId}
					role="menu"
					data-variant={variant}
				>
					<div className="account__who">
						<span className="account__who-name">{name}</span>
						{email ? <span className="account__who-email">{email}</span> : null}
					</div>
					{confirming ? (
						<>
							<p className="account__confirm">
								Your chats stay on this account. Sign back in any time to pick
								them up.
							</p>
							<button
								type="button"
								className="account__item account__item--danger"
								role="menuitem"
								onClick={handleSignOut}
							>
								Yes, sign out
							</button>
							<button
								type="button"
								className="account__item"
								role="menuitem"
								onClick={() => setConfirming(false)}
							>
								Stay signed in
							</button>
						</>
					) : (
						<button
							type="button"
							className="account__item"
							role="menuitem"
							// Confirmed rather than immediate: from here it is not obvious what happens to the conversations in the rail, a…
							onClick={() => setConfirming(true)}
						>
							Sign out
						</button>
					)}
				</div>
			) : null}
		</div>
	);
}

/** The same device mark the signed-out foot has always used. */
function DeviceGlyph() {
	return (
		<svg
			width="18"
			height="18"
			viewBox="0 0 24 24"
			fill="none"
			stroke="currentColor"
			strokeWidth="1.8"
			strokeLinecap="round"
			strokeLinejoin="round"
			aria-hidden="true"
		>
			<rect x="2" y="4" width="20" height="13" rx="2" />
			<path d="M8 21h8M12 17v4" />
		</svg>
	);
}
