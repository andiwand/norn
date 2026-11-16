<script lang="ts">
	// What a pan/tilt camera does by itself: follow people, patrol through presets, turn to a
	// preset when something is detected. Saved with the camera.
	import { untrack } from 'svelte';
	import { api, cameraBody, type Camera, type Patrol, type Reaction } from '../api';
	import { triggerLabel } from '../format';
	import { store } from '../state.svelte';
	import ChoiceSetting from './ChoiceSetting.svelte';
	import NumberSetting from './NumberSetting.svelte';
	import ScheduleSetting from './ScheduleSetting.svelte';
	import Plus from '@lucide/svelte/icons/plus';
	import X from '@lucide/svelte/icons/x';

	let { camera }: { camera: Camera } = $props();

	const initial = untrack(() => camera);
	let follow = $state(initial.follow ?? 'off');
	// Copies of the camera's (reactive) settings, to edit until Save.
	let patrol = $state<Patrol>(
		$state.snapshot(
			initial.patrol ?? {
				enabled: false,
				presets: [],
				order: 'sequence',
				dwell_seconds: 60,
				schedule: [],
				pause_after_manual: 120
			}
		)
	);
	let reactions = $state<Reaction[]>($state.snapshot(initial.reactions ?? []));
	let saving = $state(false);

	const presets = $derived(Object.entries(camera.presets_norn ?? {}));
	const tracksItself = $derived(
		store.controls[camera.id]?.controls.some((c) => c.id === 'autotrack')
	);
	// Changed since the form opened: only then a Save button.
	const baseline = JSON.stringify(untrack(() => [follow, patrol, reactions]));
	const dirty = $derived(JSON.stringify([follow, patrol, reactions]) !== baseline);

	function togglePatrolPreset(id: string) {
		patrol.presets = patrol.presets.includes(id)
			? patrol.presets.filter((p) => p !== id)
			: [...patrol.presets, id];
	}
	function toggle<T>(list: T[], item: T): T[] {
		return list.includes(item) ? list.filter((x) => x !== item) : [...list, item];
	}

	async function save() {
		saving = true;
		const body = cameraBody(camera, {
			follow,
			patrol: patrol.presets.length || patrol.enabled ? $state.snapshot(patrol) : null,
			reactions: $state.snapshot(reactions).filter((r) => r.kinds.length && r.presets.length)
		});
		const ok = await store.attempt(() => api.updateCamera(camera.id, body), 'Saved');
		saving = false;
		if (ok) store.refresh();
	}
</script>

<div class="-mx-4 divide-y divide-line">
	<ChoiceSetting
		label="Follow people"
		hint={tracksItself
			? 'With the camera’s own tracking.'
			: 'Norn turns the camera toward the person it sees (needs object detection).'}
		bind:value={follow}
		choices={[
			['off', 'Off'],
			['recording', 'Recording'],
			['away', 'Away'],
			['always', 'Always']
		]}
	/>

	<div class="px-5 py-3.5">
		<label class="flex cursor-pointer items-center justify-between gap-4">
			<span>
				<span class="block text-sm font-medium">Patrol</span>
				<span class="block text-xs text-muted"
					>Turn through presets by itself; waits while someone steers.</span
				>
			</span>
			<input type="checkbox" role="switch" class="switch" bind:checked={patrol.enabled} />
		</label>
		{#if patrol.enabled}
			{#if presets.length}
				<p class="mt-3 mb-1.5 text-xs text-muted">Presets, in this order:</p>
				<div class="flex flex-wrap gap-1.5">
					{#each presets as [id, preset] (id)}
						{@const n = patrol.presets.indexOf(id)}
						<button
							type="button"
							class="chip {n >= 0 ? 'chip-active' : ''}"
							onclick={() => togglePatrolPreset(id)}
							>{#if n >= 0}<span class="tabular-nums">{n + 1}.</span>{/if}{preset.name}</button
						>
					{/each}
				</div>
			{:else}
				<p class="mt-2 text-xs text-warning">Save some presets first (above).</p>
			{/if}
		{/if}
	</div>
	{#if patrol.enabled}
		<ChoiceSetting
			label="Order"
			bind:value={patrol.order}
			choices={[
				['sequence', 'In turn'],
				['random', 'At random']
			]}
		/>
		<NumberSetting label="Stay at each" bind:value={patrol.dwell_seconds} min={5} unit="sec" />
		<ScheduleSetting label="When it patrols" bind:value={patrol.schedule as never} />
	{/if}

	<div class="px-5 py-3.5">
		<div class="flex items-center justify-between gap-4">
			<span>
				<span class="block text-sm font-medium">Reactions</span>
				<span class="block text-xs text-muted"
					>When something is detected, turn to a preset for a while.</span
				>
			</span>
			<button
				type="button"
				class="chip"
				disabled={!presets.length}
				onclick={() =>
					(reactions = [
						...reactions,
						{ kinds: ['person'], cameras: [], presets: [], hold_seconds: 60 }
					])}><Plus class="size-3.5" />Reaction</button
			>
		</div>
		{#each reactions as r, i (i)}
			<div class="mt-2 space-y-2 rounded-xl bg-surface-2/60 p-3 text-xs">
				<div class="flex items-start justify-between gap-2">
					<div class="flex flex-wrap items-center gap-1.5">
						<span class="text-muted">When</span>
						{#each store.labels as label (label.id)}
							<button
								type="button"
								class="chip h-7 {r.kinds.includes(label.id) ? 'chip-active' : ''}"
								onclick={() => (r.kinds = toggle(r.kinds, label.id))}>{label.name}</button
							>
						{/each}
					</div>
					<button
						type="button"
						class="icon-btn size-7"
						aria-label="Remove"
						onclick={() => (reactions = reactions.filter((_, n) => n !== i))}
						><X class="size-4" /></button
					>
				</div>
				<div class="flex flex-wrap items-center gap-1.5">
					<span class="text-muted">on</span>
					{#each store.cameras as c (c.id)}
						{@const own = c.id === camera.id}
						<button
							type="button"
							class="chip h-7 {(own && !r.cameras.length) || r.cameras.includes(c.id)
								? 'chip-active'
								: ''}"
							onclick={() => (r.cameras = toggle(r.cameras, c.id))}
							>{own ? 'this camera' : c.name}</button
						>
					{/each}
				</div>
				<div class="flex flex-wrap items-center gap-1.5">
					<span class="text-muted">turn to</span>
					{#each presets as [id, preset] (id)}
						<button
							type="button"
							class="chip h-7 {r.presets.includes(id) ? 'chip-active' : ''}"
							onclick={() => (r.presets = toggle(r.presets, id))}>{preset.name}</button
						>
					{/each}
					<span class="text-muted">for</span>
					<input
						type="number"
						class="field h-7 w-16 px-2 text-right tabular-nums"
						min="5"
						max="3600"
						bind:value={r.hold_seconds}
						aria-label="Seconds"
					/>
					<span class="text-muted">sec{r.presets.length > 1 ? ' (one at random)' : ''}</span>
				</div>
				{#if !r.kinds.length || !r.presets.length}
					<p class="text-warning">Pick at least one detection and one preset.</p>
				{/if}
				<span class="sr-only">{r.kinds.map(triggerLabel).join(', ')}</span>
			</div>
		{/each}
	</div>

	{#if dirty}
		<div class="flex justify-end px-5 py-3">
			<button class="btn-primary h-9" onclick={save} disabled={saving}
				>{saving ? 'Saving…' : 'Save'}</button
			>
		</div>
	{/if}
</div>
