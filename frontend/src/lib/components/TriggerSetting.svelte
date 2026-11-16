<script lang="ts">
	// Which detections start a clip: chips to pick from. With `inherit`, null means "as set
	// above" (the global or circle value, `inherit`).
	import { triggerLabel } from '../format';
	import { store } from '../state.svelte';

	let {
		label,
		hint = '',
		value = $bindable(),
		kinds,
		inherit
	}: {
		label: string;
		hint?: string;
		value: string[] | null;
		/** What can be picked: a camera's own kinds; all labels when left out (generic triggers). */
		kinds?: string[];
		inherit?: string[];
	} = $props();

	const own = $derived(value !== null);
	const shown = $derived(value ?? inherit ?? []);
	const all = $derived(store.labels.map((l) => l.id));
	const offered = $derived(kinds ?? all);
	const choices = $derived(all.filter((k) => offered.includes(k) || shown.includes(k)));

	function toggle(kind: string) {
		const current = value ?? [...(inherit ?? [])];
		value = current.includes(kind) ? current.filter((k) => k !== kind) : [...current, kind];
	}
</script>

<div class="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 px-5 py-3.5">
	<div class="min-w-0 flex-1 basis-56">
		<span class="block text-sm font-medium">{label}</span>
		<span class="mt-0.5 block text-xs text-muted">
			{hint}
			{#if inherit !== undefined && !own}As set above.{/if}
			{#if !choices.length}This camera reports no detections.{/if}
		</span>
	</div>
	<div class="flex w-full shrink-0 flex-wrap items-center justify-end gap-1.5 sm:w-60">
		{#each choices as kind (kind)}
			{@const on = shown.includes(kind)}
			<button
				type="button"
				role="switch"
				aria-checked={on}
				class="chip {on ? 'chip-active' : ''} {own || inherit === undefined ? '' : 'opacity-60'}"
				title={offered.includes(kind)
					? (store.labels.find((l) => l.id === kind)?.description ?? '')
					: "This camera doesn't report it"}
				onclick={() => toggle(kind)}>{triggerLabel(kind)}</button
			>
		{/each}
		{#if inherit !== undefined && own}
			<button type="button" class="chip border-dashed" onclick={() => (value = null)}
				>Default</button
			>
		{/if}
	</div>
</div>
