/** The device's running Tin total, so My Journey shows one tin across chats. */

const KEY = "aspire.tin.v1";

export function tinTotal(): number {
	try {
		return Math.max(0, Number(localStorage.getItem(KEY)) || 0);
	} catch {
		return 0;
	}
}

export function addCoins(delta: number): void {
	try {
		localStorage.setItem(KEY, String(tinTotal() + Math.max(0, delta)));
	} catch {
		// The drop still showed; the shelf just forgets.
	}
}
