<script lang="ts">
	// Norn's presets of a pan/tilt camera: a picture each, a click goes there. "Save this view"
	// stores what the camera shows now (and, if wanted, its current settings) as a preset. The
	// star marks the default: where the camera returns when nothing else steers it. Star and
	// delete show on hover; touch screens, which can't hover, always show them.
	import { api, urls, type Camera, type Control } from '../api';
	import { slugify } from '../format';
	import { store } from '../state.svelte';
	import Plus from '@lucide/svelte/icons/plus';
	import X from '@lucide/svelte/icons/x';
	import Star from '@lucide/svelte/icons/star';

	let { camera, controls }: { camera: Camera; controls: Control[] } = $props();

	const presets = $derived(Object.entries(camera.presets_norn ?? {}));
	const canSave = $derived(camera.capabilities.includes('preset-save'));
	const settable = $derived(controls.filter((c) => c.kind !== 'button'));

	let adding = $state(false);
	let name = $state('');
	let keep = $state<string[]>([]);
	let saving = $state(false);
	let version = $state(Date.now()); // pictures change when a preset is saved again
	// Deleting takes a second tap within a few seconds.
	let confirming = $state<string | null>(null);
	let confirmTimer: ReturnType<typeof setTimeout> | undefined;

	async function save(e: SubmitEvent) {
		e.preventDefault();
		const id = slugify(name) || `preset-${Date.now().toString(36)}`;
		saving = true;
		const ok = await store.attempt(
			() => api.savePreset(camera.id, id, { name: name.trim(), controls: keep }),
			`Saved “${name.trim()}”`
		);
		saving = false;
		if (ok) {
			adding = false;
			name = '';
			keep = [];
			version = Date.now();
			store.refresh();
		}
	}

	async function setDefault(id: string) {
		const next = camera.default_preset === id ? null : id;
		const ok = await store.attempt(
			() => api.setDefaultPreset(camera.id, next),
			next ? `“${camera.presets_norn[id].name}” is the default` : 'No default preset'
		);
		if (ok) store.refresh();
	}

	async function remove(id: string) {
		clearTimeout(confirmTimer);
		if (confirming !== id) {
			confirming = id;
			confirmTimer = setTimeout(() => (confirming = null), 3000);
			return;
		}
		confirming = null;
		const ok = await store.attempt(async () => {
			await api.deletePreset(camera.id, id);
			return true;
		});
		if (ok) store.refresh();
	}
</script>

{#if presets.length || canSave}
	<div class="mt-5">
		<div class="mb-2 text-xs font-medium text-muted">Norn presets</div>
		<div class="grid grid-cols-2 gap-2">
			{#each presets as [id, preset] (id)}
				{@const isDefault = camera.default_preset === id}
				<div class="group/preset relative">
					<button
						class="group block w-full overflow-hidden rounded-xl border border-line bg-surface-2 text-left"
						onclick={() =>
							store.attempt(() => api.gotoPreset(camera.id, id), `Going to “${preset.name}”`)}
						title={Object.keys(preset.controls).length
							? `Also sets: ${Object.keys(preset.controls).join(', ')}`
							: ''}
					>
						<img
							src={urls.presetPicture(camera.id, id, version)}
							alt=""
							class="aspect-video w-full bg-black object-cover transition group-hover:opacity-90"
							onerror={(e) => ((e.currentTarget as HTMLImageElement).style.visibility = 'hidden')}
						/>
						<span class="block truncate px-2 py-1.5 text-xs font-medium"
							>{preset.name}{#if isDefault}<span class="font-normal text-muted">
									· default</span
								>{/if}</span
						>
					</button>
					<!-- With a mouse: on hover (the default's star always). Touch: always. -->
					<button
						class="absolute top-1 left-1 tile-action transition {isDefault
							? 'text-warning'
							: 'pointer-fine:opacity-0 pointer-fine:group-hover/preset:opacity-100 pointer-fine:focus-visible:opacity-100'}"
						aria-label={isDefault ? 'No default preset' : `Make “${preset.name}” the default`}
						aria-pressed={isDefault}
						title={isDefault
							? 'The default: Norn returns here when nothing else steers the camera'
							: 'Make it the default: Norn returns here when nothing else steers the camera'}
						onclick={() => setDefault(id)}
						><Star class="size-4 {isDefault ? 'fill-current' : ''}" /></button
					>
					<button
						class="absolute top-1 right-1 tile-action transition hover:bg-danger {confirming === id
							? 'w-auto! bg-danger px-2 text-xs font-medium'
							: 'pointer-fine:opacity-0 pointer-fine:group-hover/preset:opacity-100 pointer-fine:focus-visible:opacity-100'}"
						aria-label={confirming === id
							? `Really delete ${preset.name}`
							: `Delete ${preset.name}`}
						onclick={() => remove(id)}
						>{#if confirming === id}Delete?{:else}<X class="size-4" />{/if}</button
					>
				</div>
			{/each}
		</div>
		{#if canSave}
			{#if adding}
				<form class="mt-3 space-y-2 rounded-xl bg-surface-2/60 p-3" onsubmit={save}>
					<input
						class="input h-9"
						bind:value={name}
						placeholder="Name, e.g. Front door"
						required
						maxlength="40"
					/>
					{#if settable.length}
						<p class="text-xs text-muted">Also apply these settings as they are now:</p>
						<div class="flex flex-wrap gap-1.5">
							{#each settable as c (c.id)}
								<label class="chip cursor-pointer has-[:checked]:chip-active">
									<input type="checkbox" class="sr-only" bind:group={keep} value={c.id} />{c.label}
								</label>
							{/each}
						</div>
					{/if}
					<div class="flex justify-end gap-2 pt-1">
						<button type="button" class="btn-ghost h-9" onclick={() => (adding = false)}
							>Cancel</button
						>
						<button class="btn-primary h-9" disabled={saving || !name.trim()}
							>{saving ? 'Saving…' : 'Save this view'}</button
						>
					</div>
				</form>
			{:else}
				<button class="mt-2 chip border-dashed" onclick={() => (adding = true)}
					><Plus class="size-3.5" />Save this view</button
				>
			{/if}
		{/if}
	</div>
{/if}
