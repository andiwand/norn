// Recordings shown on a page, with the actions on them, and the clock their lifetime rings follow.
import { createSubscriber } from 'svelte/reactivity';
import { api, type Recording } from './api';
import { store } from './state.svelte';

/** Delete a recording; whether it worked (an error shows as a toast). */
export async function deleteRecording(r: Recording): Promise<boolean> {
	const ok = await store.attempt(
		() => api.deleteRecording(r.id).then(() => true),
		'Recording deleted'
	);
	return !!ok;
}

/** A list of recordings that pinning and deleting update in place. */
export class RecordingList {
	items = $state<Recording[]>([]);

	/** Put in a recording's new state. */
	replace = (updated: Recording) => {
		this.items = this.items.map((x) => (x.id === updated.id ? updated : x));
	};

	drop = (r: Recording) => {
		this.items = this.items.filter((x) => x.id !== r.id);
	};

	pin = async (r: Recording, pinned: boolean) => {
		const updated = await store.pin(r, pinned);
		if (updated) this.replace(updated);
	};

	remove = async (r: Recording) => {
		if (await deleteRecording(r)) this.drop(r);
	};
}

const minutes = createSubscriber((update) => {
	const timer = setInterval(update, 60_000);
	return () => clearInterval(timer);
});

/** The time, for countdowns: what reads it updates every minute. */
export const clock = {
	get now() {
		minutes();
		return Date.now();
	}
};
