<script lang="ts">
	// What a camera detects right now, and who sees it: "Person · camera", "Person · Norn",
	// "Person · camera + Norn". A person said only by the camera, while Norn's AI looks and sees
	// nobody, may well be a false alarm: the badge tells them apart.
	import { sourcesLabel, triggerLabel } from '../format';

	let { active, by = {} }: { active: string[]; by?: Record<string, string[]> } = $props();
	// The most telling one first: a person says more than motion.
	const shown = $derived(
		active.filter((k) => k !== 'motion').concat(active.includes('motion') ? ['motion'] : [])
	);
	// Who sees them: said once when it is the same for all, else for each.
	const who = $derived(shown.map((k) => sourcesLabel(by[k])));
	const same = $derived(who.every((w) => w === who[0]));
	const text = $derived(
		same
			? shown.map(triggerLabel).join(' · ') + (who[0] ? ` · ${who[0]}` : '')
			: shown
					.map((k, i) => (who[i] ? `${triggerLabel(k)} (${who[i]})` : triggerLabel(k)))
					.join(' · ')
	);
	const title = $derived(
		shown.map((k, i) => `${triggerLabel(k)}${who[i] ? `: seen by ${who[i]}` : ''}`).join('; ')
	);
</script>

{#if shown.length}
	<!-- Like the REC badge: dark glass on the video, with a dot in the second accent colour. -->
	<span
		class="inline-flex max-w-full items-center gap-1.5 rounded-full bg-black/55 px-2.5 py-1 text-[11px] font-semibold text-white backdrop-blur-md"
		{title}
	>
		<span class="rec-dot size-2 shrink-0 rounded-full bg-accent-2"></span><span class="truncate"
			>{text}</span
		>
	</span>
{/if}
