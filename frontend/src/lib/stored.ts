// Things this browser remembers (localStorage). Only conveniences: in a private window, or with
// the storage full or blocked, they are simply not kept.

export function readStored(key: string): string | null {
	try {
		return localStorage.getItem(key);
	} catch {
		return null;
	}
}

export function readStoredJson<T>(key: string, fallback: T): T {
	try {
		return JSON.parse(readStored(key) ?? '') ?? fallback;
	} catch {
		return fallback;
	}
}

export function writeStored(key: string, value: string) {
	try {
		localStorage.setItem(key, value);
	} catch {
		// not kept
	}
}
