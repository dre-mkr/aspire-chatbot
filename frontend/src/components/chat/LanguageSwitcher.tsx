import { HOOK_LANGUAGES, type HookLanguage } from "#/lib/aspire/hooks";

/**
 * EN · ES · FR, in the corner.
 *
 * THREE BUTTONS RATHER THAN A MENU, because there are three of them and a menu
 * would hide two behind a click to save a few pixels. Corner rather than beside
 * the guide picker, which already carries the guide's face, their name, the
 * band they answer at and a change control -- a fourth thing there is the one
 * that makes it a cluster.
 *
 * WHAT `selected` MEANS. There is no fourth "Auto" button, and that is
 * deliberate. The reader is always being answered in exactly one language, so
 * the control shows which one rather than which policy chose it. Until someone
 * picks, that language is whatever the conversation has been in -- English
 * unless the reader wrote or spoke Spanish or French, in which case ASPIRE
 * already followed them and the highlight moves on its own.
 *
 * Picking one also leaves Automatic, in `setLanguage`. Choosing Español and
 * then being answered in English because the last message happened to be in
 * English is the control not working, whatever it looks like.
 */
export function LanguageSwitcher({
	selected,
	onChoose,
}: {
	selected: HookLanguage;
	onChoose: (language: HookLanguage) => void;
}) {
	return (
		/* A fieldset rather than a div with `role="group"`: it is the semantic
		   element for exactly this, and the legend gives the group its name
		   without a second label to keep in step. */
		<fieldset className="lang-switch">
			<legend className="sr-only">Language ASPIRE answers in</legend>
			{HOOK_LANGUAGES.map((language) => (
				<button
					key={language.id}
					type="button"
					className="lang-switch__option"
					aria-pressed={language.id === selected}
					/* The code is what is shown and the name is what is announced:
					   "ES" read aloud is a spelling, not a language. */
					aria-label={language.native}
					title={language.native}
					onClick={() => onChoose(language.id)}
				>
					{language.label}
				</button>
			))}
		</fieldset>
	);
}
