<script lang="ts">
	// How much of a recording's lifetime is left, as a ring that empties until Norn deletes it.
	import { formatRemaining } from '../format';
	import { clock } from '../recordings.svelte';

	let {
		start,
		expires,
		class: className = ''
	}: { start: string; expires: string; class?: string } = $props();

	const total = $derived(new Date(expires).getTime() - new Date(start).getTime());
	const left = $derived(Math.max(0, new Date(expires).getTime() - clock.now));
	const fraction = $derived(total > 0 ? Math.min(1, left / total) : 0);
	const r = 7;
	const circumference = 2 * Math.PI * r;
	const label = $derived(`Deleted in ${formatRemaining(left)}`);
</script>

<span
	class="grid size-7 place-items-center rounded-full bg-black/50 backdrop-blur-md {className}"
	title={label}
	aria-label={label}
	role="img"
>
	<svg viewBox="0 0 18 18" class="size-[18px] -rotate-90">
		<circle cx="9" cy="9" {r} fill="none" stroke="white" stroke-opacity="0.25" stroke-width="2.5" />
		<circle
			cx="9"
			cy="9"
			{r}
			fill="none"
			stroke={fraction < 0.15 ? 'var(--warning)' : 'white'}
			stroke-width="2.5"
			stroke-linecap="round"
			stroke-dasharray={circumference}
			stroke-dashoffset={circumference * (1 - fraction)}
		/>
	</svg>
</span>
