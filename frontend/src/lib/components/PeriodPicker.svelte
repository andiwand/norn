<script lang="ts" generics="T extends string | number">
	// How much time a card shows: one look and one place everywhere (the right end of the card's
	// header): the activity of a camera, the heat map of the recordings, the timeline.
	let {
		options,
		value,
		onpick,
		label = 'Period'
	}: {
		options: readonly (readonly [T, string])[];
		value: T;
		onpick: (value: T) => void;
		label?: string;
	} = $props();
</script>

<div class="flex shrink-0 rounded-xl bg-surface-3 p-1" role="radiogroup" aria-label={label}>
	{#each options as [v, text] (v)}
		<button
			role="radio"
			aria-checked={value === v}
			class="rounded-lg px-2.5 py-1 text-xs font-medium whitespace-nowrap transition {value === v
				? 'bg-surface text-text shadow'
				: 'text-muted hover:text-text'}"
			onclick={() => onpick(v)}>{text}</button
		>
	{/each}
</div>
