import { currentLocale } from "#/lib/aspire/i18n";
import { viewsCopy } from "#/lib/aspire/views-copy";
import { ViewHeader } from "./ViewHeader";

/** Pictures and video from the programme — a page that says so before it has them. */
export function GalleryView({
	onBack,
	backLabel,
}: {
	onBack: () => void;
	backLabel?: string;
}) {
	const copy = viewsCopy(currentLocale()).gallery;
	return (
		<div className="view">
			<ViewHeader onBack={onBack} backLabel={backLabel} />
			<main className="view__main">
				<div className="view__head">
					<h1 className="view__title">{copy.title}</h1>
					<p className="view__lede">{copy.lede}</p>
				</div>

				<div className="panel-row">
					<section className="panel gallery-panel">
						<span className="panel__icon" aria-hidden="true">
							<i className="ph-duotone ph-images" />
						</span>
						<h2 className="panel__title">{copy.photosTitle}</h2>
						<p>{copy.photosBody}</p>
						<span className="gallery-soon">{copy.comingSoon}</span>
					</section>

					<section className="panel gallery-panel">
						<span className="panel__icon" aria-hidden="true">
							<i className="ph-duotone ph-film-strip" />
						</span>
						<h2 className="panel__title">{copy.videosTitle}</h2>
						<p>{copy.videosBody}</p>
						<span className="gallery-soon">{copy.comingSoon}</span>
					</section>
				</div>
			</main>
		</div>
	);
}
