<script lang="ts">
	// What a camera detects right now: "Motion", "Person", ...
	import { triggerLabel } from '../format';

	let { active }: { active: string[] } = $props();
	// The most telling one: a person says more than motion.
	const shown = $derived(
		active.filter((k) => k !== 'motion').concat(active.includes('motion') ? ['motion'] : [])
	);
</script>

{#if shown.length}
	<!-- Like the REC badge: dark glass on the video, with a dot in the second accent colour. -->
	<span
		class="inline-flex items-center gap-1.5 rounded-full bg-black/55 px-2.5 py-1 text-[11px] font-semibold text-white backdrop-blur-md"
		title="Detects {shown.map(triggerLabel).join(', ')}"
	>
		<span class="rec-dot size-2 rounded-full bg-accent-2"></span>{shown
			.map(triggerLabel)
			.join(' · ')}
	</span>
{/if}
