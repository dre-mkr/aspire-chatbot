import type { SVGProps } from "react";

/** Line icons drawn on a 24px grid, stroked in `currentColor` so they inherit whatever the surrounding chrome is… */
type IconProps = SVGProps<SVGSVGElement> & { size?: number };

function Icon({ size = 18, strokeWidth = 1.9, children, ...rest }: IconProps) {
	return (
		<svg
			width={size}
			height={size}
			viewBox="0 0 24 24"
			fill="none"
			stroke="currentColor"
			strokeWidth={strokeWidth}
			strokeLinecap="round"
			strokeLinejoin="round"
			aria-hidden="true"
			focusable="false"
			{...rest}
		>
			{children}
		</svg>
	);
}

export function PanelLeftIcon(props: IconProps) {
	return (
		<Icon {...props}>
			<rect x="3" y="3" width="18" height="18" rx="3" />
			<path d="M9 3v18" />
		</Icon>
	);
}

export function PlusIcon(props: IconProps) {
	return (
		<Icon {...props}>
			<path d="M5 12h14" />
			<path d="M12 5v14" />
		</Icon>
	);
}

export function ClockIcon(props: IconProps) {
	return (
		<Icon {...props}>
			<path d="M12 8v4l3 2" />
			<circle cx="12" cy="12" r="9" />
		</Icon>
	);
}

/** A wrong answer that taught something. A bulb, not a cross. */
export function LampIcon(props: IconProps) {
	return (
		<Icon size={16} {...props}>
			<path d="M9 18h6" />
			<path d="M10 22h4" />
			<path d="M12 2a7 7 0 0 0-4 12.7V17h8v-2.3A7 7 0 0 0 12 2z" />
		</Icon>
	);
}

/** An answer asked for rather than attempted. */
export function EyeIcon(props: IconProps) {
	return (
		<Icon size={16} {...props}>
			<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7z" />
			<circle cx="12" cy="12" r="3" />
		</Icon>
	);
}

/** Leaving a game — a door with an arrow through it. */
export function ExitIcon(props: IconProps) {
	return (
		<Icon size={15} {...props}>
			<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
			<path d="M16 17l5-5-5-5" />
			<path d="M21 12H9" />
		</Icon>
	);
}

export function DownloadIcon(props: IconProps) {
	return (
		<Icon size={15} {...props}>
			<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
			<path d="M7 10l5 5 5-5" />
			<path d="M12 15V3" />
		</Icon>
	);
}

/** Marks where the transcript actually lives: this device, not an account. */
export function DeviceIcon(props: IconProps) {
	return (
		<Icon size={16} {...props}>
			<rect x="3" y="4" width="18" height="12" rx="2" />
			<path d="M12 16v4" />
			<path d="M8 20h8" />
		</Icon>
	);
}

/** Who the answer is for. Head and shoulders, the plainest reading of it. */
export function PersonIcon(props: IconProps) {
	return (
		<Icon size={16} {...props}>
			<circle cx="12" cy="8" r="3.4" />
			<path d="M5.5 20a6.5 6.5 0 0 1 13 0" />
		</Icon>
	);
}

export function ChevronDownIcon(props: IconProps) {
	return (
		<Icon size={14} {...props}>
			<path d="m6 9 6 6 6-6" />
		</Icon>
	);
}

export function CopyIcon(props: IconProps) {
	return (
		<Icon size={15} {...props}>
			<rect x="9" y="9" width="12" height="12" rx="3" />
			<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
		</Icon>
	);
}

export function CheckIcon(props: IconProps) {
	return (
		<Icon size={15} {...props}>
			<path d="m4 12.5 5 5L20 6.5" />
		</Icon>
	);
}

export function RetryIcon(props: IconProps) {
	return (
		<Icon size={14} {...props}>
			<path d="M3 12a9 9 0 1 0 3-6.7" />
			<path d="M3 4v5h5" />
		</Icon>
	);
}

export function SparkIcon(props: IconProps) {
	return (
		<Icon size={15} {...props}>
			<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z" />
		</Icon>
	);
}

/** Re-orders the letter tray. Crossed arrows, the shuffle convention. */
export function ShuffleIcon(props: IconProps) {
	return (
		<Icon size={16} {...props}>
			<path d="M16 3h5v5" />
			<path d="M4 20 21 3" />
			<path d="M21 16v5h-5" />
			<path d="m15 15 6 6" />
			<path d="M4 4l5 5" />
		</Icon>
	);
}

export function SendIcon(props: IconProps) {
	return (
		<Icon size={18} {...props}>
			<path d="M12 19V5" />
			<path d="M5 12l7-7 7 7" />
		</Icon>
	);
}

export function PencilIcon(props: IconProps) {
	return (
		<Icon size={16} {...props}>
			<path d="M4 20h4l10-10a2.5 2.5 0 0 0-3.5-3.5L4.5 16.5z" />
			<path d="M13.5 7.5 16.5 10.5" />
		</Icon>
	);
}

/* Delete, in the rail's row menu. */
export function TrashIcon(props: IconProps) {
	return (
		<Icon size={16} {...props}>
			<path d="M4 7h16" />
			<path d="M9 7V5.5A1.5 1.5 0 0 1 10.5 4h3A1.5 1.5 0 0 1 15 5.5V7" />
			<path d="M6.5 7l.8 11a2 2 0 0 0 2 1.9h5.4a2 2 0 0 0 2-1.9l.8-11" />
			<path d="M10.5 11v5.5" />
			<path d="M13.5 11v5.5" />
		</Icon>
	);
}

/* The per-conversation overflow trigger in the rail. */
export function MoreIcon(props: IconProps) {
	return (
		<Icon size={17} {...props}>
			<circle cx="5" cy="12" r="1.6" fill="currentColor" stroke="none" />
			<circle cx="12" cy="12" r="1.6" fill="currentColor" stroke="none" />
			<circle cx="19" cy="12" r="1.6" fill="currentColor" stroke="none" />
		</Icon>
	);
}

/* Sliders, deliberately not a mic variant: this opens voice *settings* and it sits two controls away from the a… */
export function SlidersIcon(props: IconProps) {
	return (
		<Icon size={17} {...props}>
			<path d="M4 7h9" />
			<path d="M17 7h3" />
			<path d="M4 17h3" />
			<path d="M11 17h9" />
			<circle cx="15" cy="7" r="2.2" />
			<circle cx="9" cy="17" r="2.2" />
		</Icon>
	);
}

/* Filled rather than stroked, unlike its neighbours: stop is the one control here that halts something already… */
export function StopIcon(props: IconProps) {
	return (
		<Icon size={16} {...props}>
			<rect x="6" y="6" width="12" height="12" rx="2.5" fill="currentColor" />
		</Icon>
	);
}

export function MenuIcon(props: IconProps) {
	return (
		<Icon size={17} {...props}>
			<path d="M4 6h16" />
			<path d="M4 12h16" />
			<path d="M4 18h16" />
		</Icon>
	);
}

export function MicIcon(props: IconProps) {
	return (
		<Icon size={18} {...props}>
			<path d="M12 2a3 3 0 0 1 3 3v6a3 3 0 0 1-6 0V5a3 3 0 0 1 3-3z" />
			<path d="M19 10v1a7 7 0 0 1-14 0v-1" />
			<path d="M12 18v4" />
		</Icon>
	);
}

/** Reads an answer aloud. A speaker, not a media play triangle. */
export function SpeakerIcon(props: IconProps) {
	return (
		<Icon size={14} {...props}>
			<path d="M11 5 6 9H3v6h3l5 4z" />
			<path d="M16 9a4 4 0 0 1 0 6" />
			<path d="M19 6a8 8 0 0 1 0 12" />
		</Icon>
	);
}

export function PauseIcon(props: IconProps) {
	return (
		<Icon size={14} {...props}>
			<rect x="6" y="4" width="4" height="16" rx="1" />
			<rect x="14" y="4" width="4" height="16" rx="1" />
		</Icon>
	);
}

export function CloseIcon(props: IconProps) {
	return (
		<Icon size={16} {...props}>
			<path d="M18 6 6 18" />
			<path d="m6 6 12 12" />
		</Icon>
	);
}

export function InfoIcon(props: IconProps) {
	return (
		<Icon size={14} {...props}>
			<circle cx="12" cy="12" r="9" />
			<path d="M12 16v-4" />
			<path d="M12 8h.01" />
		</Icon>
	);
}

/** Marks the knowledge-base extracts an answer was drawn from. */
export function SourcesIcon(props: IconProps) {
	return (
		<Icon size={15} {...props}>
			<path d="M4 5.5A1.5 1.5 0 0 1 5.5 4H10a2 2 0 0 1 2 2v13a1.5 1.5 0 0 0-1.5-1.5h-5A1.5 1.5 0 0 1 4 16z" />
			<path d="M20 5.5A1.5 1.5 0 0 0 18.5 4H14a2 2 0 0 0-2 2v13a1.5 1.5 0 0 1 1.5-1.5h5A1.5 1.5 0 0 0 20 16z" />
		</Icon>
	);
}

/** Fronts a failed turn. */
export function AlertIcon(props: IconProps) {
	return (
		<Icon size={16} {...props}>
			<circle cx="12" cy="12" r="8.5" />
			<path d="M12 8v4.5" />
			<path d="M12 15.75h.01" />
		</Icon>
	);
}
