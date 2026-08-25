/** The reader's story artifacts, kept on this device so My Journey can shelve them. */

const KEY = "aspire.collectibles.v1";

export interface Collectible {
	name: string;
	emoji: string;
	topic: string;
}

export function collection(): Collectible[] {
	try {
		const raw = localStorage.getItem(KEY);
		const parsed = raw ? JSON.parse(raw) : [];
		return Array.isArray(parsed) ? parsed : [];
	} catch {
		return [];
	}
}

/** Adds one, once: the same artifact from the same topic is not shelved twice. */
export function collect(item: Collectible): void {
	try {
		const items = collection();
		if (items.some((c) => c.name === item.name && c.topic === item.topic))
			return;
		localStorage.setItem(KEY, JSON.stringify([...items, item]));
	} catch {
		// Storage full or blocked: the card still showed; the shelf just forgets.
	}
}
