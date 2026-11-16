// The settings as a form: a copy of the saved values to edit, saved by what changed (the server
// keeps the rest, so a change made meanwhile elsewhere isn't undone). Used by Settings and Away.
import { api, type SettingsData, type SettingsValues } from './api';
import { store } from './state.svelte';

export class SettingsForm {
	saved = $state<SettingsValues | null>(null);
	defaults = $state<SettingsValues | null>(null);
	form = $state<SettingsValues | null>(null);
	saving = $state(false);
	dirty = $derived(!!this.form && JSON.stringify(this.form) !== JSON.stringify(this.saved));

	/** Load, and follow changes made elsewhere while nothing is being edited here. */
	watch(): () => void {
		api.settings().then((d) => this.take(d));
		return store.on((e) => {
			if (['settings.changed', 'cameras.changed', 'away.changed'].includes(e.type) && !this.dirty) {
				api.settings().then((d) => this.take(d));
			}
		});
	}

	take(data: SettingsData) {
		this.saved = data.values;
		this.defaults = data.defaults;
		this.form = structuredClone(data.values);
	}

	reset() {
		if (this.saved) this.form = structuredClone($state.snapshot(this.saved));
	}

	/** Save the fields that differ from what was loaded. */
	async save(message = 'Saved') {
		if (!this.form) return;
		this.saving = true;
		const now = $state.snapshot(this.form) as unknown as Record<string, Record<string, unknown>>;
		const before = (this.saved ?? {}) as unknown as Record<string, Record<string, unknown>>;
		const changes: Record<string, Record<string, unknown>> = {};
		for (const [section, values] of Object.entries(now)) {
			for (const [key, value] of Object.entries(values)) {
				if (JSON.stringify(value) !== JSON.stringify(before[section]?.[key])) {
					(changes[section] ??= {})[key] = value;
				}
			}
		}
		const data = await store.attempt(() => api.saveSettings(changes), message);
		this.saving = false;
		if (data) this.take(data);
	}
}
