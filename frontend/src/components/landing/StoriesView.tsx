
export function StoriesView({ onBack }: { onBack: () => void }) {
  return (
    <div className="absolute inset-0 z-50 bg-white/95 backdrop-blur-xl overflow-y-auto pt-8 px-4 pb-24 md:px-8">
      <div className="max-w-5xl mx-auto">
        <button type="button" onClick={onBack} className="flex items-center gap-2 text-plum hover:text-magenta transition-colors font-semibold mb-8">
          <i className="ph-bold ph-arrow-left"></i> Back to Ecosystem
        </button>
        <div className="flex items-center gap-4 mb-8">
          <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-[#c22f99] to-[#8a1c6a] flex items-center justify-center text-white shadow-lg">
            <i className="ph-duotone ph-book-open-text text-4xl"></i>
          </div>
          <div>
            <h2 className="font-display text-4xl font-bold text-ink">Miracle Mountain</h2>
            <p className="text-slate text-lg">Interactive financial tales of St. Kitts & Nevis</p>
          </div>
        </div>

        {/* THE TWO STORIES ADVERTISED HERE DID NOT EXIST.
          *
          * "The Magic Coins" and "The Sugar Mas Budget" were invented during a
          * design pass, along with an Episode 1 / Episode 2 unlock mechanic that
          * the product has no concept of. Imani was cast as the traveller; Imani
          * is the guardian persona, not a character in anything.
          *
          * These are the two films that actually exist, with their real titles,
          * settings and running times, taken from backend/app/videos/catalog.py.
          * Neither is locked and there is nothing to unlock.
          */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="bg-white rounded-3xl border border-plum/10 shadow-[0_8px_30px_rgb(0,0,0,0.04)] overflow-hidden hover:shadow-[0_20px_40px_rgb(194,47,153,0.15)] transition-shadow cursor-pointer group">
            <div className="h-48 bg-gradient-to-br from-pink-100 to-rose-50 flex items-center justify-center group-hover:scale-105 transition-transform duration-500">
               <i className="ph-duotone ph-cloud-rain text-6xl text-pink-500"></i>
            </div>
            <div className="p-6 relative bg-white">
              <span className="text-xs font-bold uppercase tracking-wider text-magenta mb-2 block">Basseterre, St. Kitts &middot; 4 min</span>
              <h3 className="text-xl font-display font-bold text-ink mb-2">The Adventures of Captain Careful and the Quest for Scarcity</h3>
              <p className="text-slate text-sm">A thunderstorm leaves Basseterre short of supplies, and Captain Careful helps the community decide what matters most: sharing what there is, saving water, and telling a need apart from a want.</p>
            </div>
          </div>

          <div className="bg-white rounded-3xl border border-plum/10 shadow-[0_8px_30px_rgb(0,0,0,0.04)] overflow-hidden hover:shadow-[0_20px_40px_rgb(194,47,153,0.15)] transition-shadow cursor-pointer group">
            <div className="h-48 bg-gradient-to-br from-amber-100 to-yellow-50 flex items-center justify-center group-hover:scale-105 transition-transform duration-500">
               <i className="ph-duotone ph-magic-wand text-6xl text-amber-500"></i>
            </div>
            <div className="p-6 relative bg-white">
              <span className="text-xs font-bold uppercase tracking-wider text-magenta mb-2 block">Nevis &middot; 6 min</span>
              <h3 className="text-xl font-display font-bold text-ink mb-2">Monique's Saving Adventure</h3>
              <p className="text-slate text-sm">Monique lives on Nevis and wants the Wand of Wisdom, which costs 100 magic dollars. She learns that earning takes work, that time is worth something too, and that waiting for the thing you actually want beats spending on the thing you don't.</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
