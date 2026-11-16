<script lang="ts">
	// What a camera detects right now: "Motion", "Person", ...
	import { triggerLabel } from '../format';
	import Activity from '@lucide/svelte/icons/activity';

	let { active }: { active: string[] } = $props();
	// The most telling one: a person says more than motion.
	const shown = $derived(
		active.filter((k) => k !== 'motion').concat(active.includes('motion') ? ['motion'] : [])
	);
</script>

{#if shown.length}
	<span
		class="flex items-center gap-1.5 rounded-full bg-warning/90 px-2.5 py-1 text-[11px] font-semibold text-black backdrop-blur-md"
		title="Detects {shown.map(triggerLabel).join(', ')}"
	>
		<Activity class="size-3" />{shown.map(triggerLabel).join(' · ')}
	</span>
{/if}
