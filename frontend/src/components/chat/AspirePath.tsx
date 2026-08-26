/**
 * ASPIRE Path — the work, visible while it happens.
 *
 * WHAT IT IS FOR. Nothing in this product streams tokens: every word waits for
 * the outbound safety gates, because a cap, a vocabulary swap or a decline runs
 * a graph step after the agent that wrote the text, and anything already on
 * screen cannot be taken back. That is the right call and it is staying. Its
 * cost is a silence — measured on production across twenty-four turns, between
 * 1.5 and 14.7 seconds of nothing at all.
 *
 * This fills that silence with something true. Each stage lights when a real
 * node has finished: the router choosing who answers, the approved material
 * being searched, the answer being built, the turn passing its gates.
 *
 * WHAT IT DELIBERATELY IS NOT. It never shows a classifier, a retrieval score,
 * a node name or a model. A reader is shown what the work MEANS to them, in
 * their guide's own register and their own language — and the words come from
 * the server, so this component cannot invent a stage that did not happen.
 *
 * It also does not appear on every turn. A question with an answer is not a
 * journey, and drawing four stages over one is theatre.
 */

import { useEffect, useRef, useState } from "react";

export interface PathState {
	title: string;
	labels: string[];
	at: number;
	done: boolean;
}

/**
 * How long a finished Path stays before it retires.
 *
 * Not zero: a strip that vanishes the instant the answer lands never gets read,
 * and the whole point is that the reader sees the work. Not long either — it is
 * scaffolding, and scaffolding that outstays the building is clutter.
 */
const LINGER_MS = 1400;

export function AspirePath({ path }: { path: PathState | null }) {
	const [visible, setVisible] = useState(false);
	const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

	useEffect(() => {
		if (!path) {
			setVisible(false);
			return;
		}
		setVisible(true);
		clearTimeout(timer.current);
		if (path.done) {
			timer.current = setTimeout(() => setVisible(false), LINGER_MS);
		}
		return () => clearTimeout(timer.current);
	}, [path]);

	if (!path || !visible || path.labels.length === 0) return null;

	return (
		/* ONE ANNOUNCEMENT, NOT FOUR.
		 *
		 * A polite live region on the whole strip meant a screen reader heard
		 * every stage change -- four per turn -- and then the answer, which
		 * says everything the stages did. That is chatter, and it arrives
		 * during the one moment the reader is waiting to hear something real.
		 *
		 * The title is a `status`, so "Working through this" is announced once
		 * when the strip appears. The stages themselves are progress a sighted
		 * reader watches; they are `aria-hidden`, because their content is
		 * already on its way in the answer. */
		<div className="aspire-path">
			{/* `<output>` rather than a `role="status"` paragraph: it carries
			    the status role natively, and the linter is right that the
			    element should say what it is. */}
			<output className="aspire-path__title">{path.title}</output>
			<ol className="aspire-path__stages" aria-hidden="true">
				{path.labels.map((label, index) => {
					const state =
						path.done || index < path.at
							? "done"
							: index === path.at
								? "active"
								: "waiting";
					return (
						<li key={label} className="aspire-path__stage" data-state={state}>
							<span className="aspire-path__dot" aria-hidden="true" />
							<span className="aspire-path__label">{label}</span>
						</li>
					);
				})}
			</ol>
		</div>
	);
}
