import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { CheckIcon, ChevronDownIcon, PersonIcon } from "#/components/icons";
import { PERSONAS, type PersonaId, personaById } from "#/lib/aspire/personas";

/** Who the assistant is talking to, chosen from the composer. */
export function PersonaPicker({
	persona,
	onChange,
}: {
	persona: PersonaId | null;
	onChange: (next: PersonaId | null) => void;
}) {
	const [open, setOpen] = useState(false);
	const [at, setAt] = useState<{ top: number; left: number } | null>(null);
	const menuId = useId();
	const wrapRef = useRef<HTMLDivElement>(null);
	const triggerRef = useRef<HTMLButtonElement>(null);
	const menuRef = useRef<HTMLDivElement>(null);

	const current = personaById(persona);

	/** Fixed positioning, anchored to the trigger. */
	const measure = (estimatedHeight: number) => {
		const trigger = triggerRef.current;
		if (!trigger) return null;
		const rect = trigger.getBoundingClientRect();
		// Above by preference: the composer is docked low and the menu should grow away from the box being typed in, no…
		let top = rect.top - 8 - estimatedHeight;
		// No room above — put it below, then clamp.
		if (top < 8) {
			top = Math.min(rect.bottom + 8, window.innerHeight - estimatedHeight - 8);
		}
		return {
			top: Math.max(8, top),
			left: Math.max(12, Math.min(rect.left, window.innerWidth - 300)),
		};
	};

	/** Five rows plus padding. Only used for the frame before the real one. */
	const ESTIMATED_MENU_PX = 400;

	// Correct against the menu's real height once it exists, so a short viewport cannot push the first option off t…
	// biome-ignore lint/correctness/useExhaustiveDependencies: `measure` reads live geometry and is recreated every render
	useLayoutEffect(() => {
		const menu = menuRef.current;
		if (!open || !menu || !at) return;
		const next = measure(menu.getBoundingClientRect().height);
		if (next && Math.abs(next.top - at.top) > 1) setAt(next);
	}, [open, at]);

	useEffect(() => {
		if (!open) return;
		const onKey = (event: KeyboardEvent) => {
			if (event.key !== "Escape") return;
			// Stopped from bubbling: Escape in the composer also blurs the field, and closing the menu should not additiona…
			event.stopPropagation();
			setOpen(false);
			triggerRef.current?.focus();
		};
		const onPointer = (event: PointerEvent) => {
			const target = event.target as Node;
			// The menu is portalled out of this subtree, so it is not inside `wrapRef` and has to be asked about separately.
			if (wrapRef.current?.contains(target)) return;
			if (menuRef.current?.contains(target)) return;
			setOpen(false);
		};
		// Fixed coordinates stop being true the moment anything moves.
		const onMove = () => setOpen(false);

		window.addEventListener("keydown", onKey, true);
		window.addEventListener("pointerdown", onPointer);
		window.addEventListener("resize", onMove);
		return () => {
			window.removeEventListener("keydown", onKey, true);
			window.removeEventListener("pointerdown", onPointer);
			window.removeEventListener("resize", onMove);
		};
	}, [open]);

	// Focus the checked option on open, so the keyboard lands where the eye does.
	useEffect(() => {
		if (!open) return;
		const menu = menuRef.current;
		if (!menu) return;
		const checked = menu.querySelector<HTMLButtonElement>(
			'[aria-checked="true"]',
		);
		(checked ?? menu.querySelector<HTMLButtonElement>("button"))?.focus();
	}, [open]);

	/** Up and down walk the options; the menu is a list, so it behaves like one. */
	function onMenuKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
		if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
		event.preventDefault();
		const items = [
			...(menuRef.current?.querySelectorAll<HTMLButtonElement>("button") ?? []),
		];
		const index = items.indexOf(document.activeElement as HTMLButtonElement);
		const next =
			event.key === "ArrowDown"
				? items[(index + 1) % items.length]
				: items[(index - 1 + items.length) % items.length];
		next?.focus();
	}

	function choose(next: PersonaId | null) {
		onChange(next);
		setOpen(false);
		triggerRef.current?.focus();
	}

	return (
		<div className="persona" ref={wrapRef}>
			<button
				ref={triggerRef}
				type="button"
				className="tool-btn persona__trigger"
				aria-haspopup="menu"
				aria-expanded={open}
				aria-controls={open ? menuId : undefined}
				onClick={() => {
					if (!open) setAt(measure(ESTIMATED_MENU_PX));
					setOpen((was) => !was);
				}}
				// The visible label is the persona's name, which on its own does not say what the control does.
				title={
					current
						? `Answering for ${current.audience}. Change who this is for.`
						: "Choose who this is for"
				}
			>
				<PersonIcon />
				<span className="persona__name">
					{current ? current.name : "Everyone"}
				</span>
				<ChevronDownIcon size={14} />
				<span className="sr-only">
					{current
						? `Answering for ${current.audience}. Change who this is for.`
						: "Choose who this is for"}
				</span>
			</button>

			{/* Portalled to <body>, and this is not optional. */}
			{open && at
				? createPortal(
						<div
							id={menuId}
							ref={menuRef}
							className="persona__menu"
							role="menu"
							aria-label="Who this is for"
							style={{ top: at.top, left: at.left }}
							onKeyDown={onMenuKeyDown}
						>
							{PERSONAS.map((option) => (
								<button
									key={option.id}
									type="button"
									role="menuitemradio"
									aria-checked={persona === option.id}
									className="persona__option"
									onClick={() => choose(option.id)}
								>
									<span className="persona__tick" aria-hidden="true">
										{persona === option.id ? <CheckIcon /> : null}
									</span>
									<span className="persona__text">
										<span className="persona__label">
											{option.name}
											<span className="persona__audience">
												{option.audience}
											</span>
										</span>
										<span className="persona__blurb">{option.blurb}</span>
									</span>
								</button>
							))}

							{/* "Not chosen" is a real state and stays reachable. */}
							<button
								type="button"
								role="menuitemradio"
								aria-checked={persona === null}
								className="persona__option persona__option--none"
								onClick={() => choose(null)}
							>
								<span className="persona__tick" aria-hidden="true">
									{persona === null ? <CheckIcon /> : null}
								</span>
								<span className="persona__text">
									<span className="persona__label">Everyone</span>
									<span className="persona__blurb">
										No particular audience. The default.
									</span>
								</span>
							</button>
						</div>,
						document.body,
					)
				: null}
		</div>
	);
}
