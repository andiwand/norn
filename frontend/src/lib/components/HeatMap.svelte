<script lang="ts">
	// Clips per camera and hour over the last day: the shape of the day at a glance. A cell with
	// clips jumps to the event they belong to.
	import type { HeatMap } from '../events';

	let {
		map,
		names,
		onpick
	}: {
		map: HeatMap;
		names: Record<string, string>;
		onpick: (camera: string, hour: number) => void;
	} = $props();

	const hourLabel = (t: number) =>
		new Date(t).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
	const total = $derived(map.rows.reduce((sum, r) => sum + r.counts.reduce((a, b) => a + b, 0), 0));
	// Labels every 6 hours, and "now" at the end.
	const labels = $derived(
		map.hours.map((t, i) => (i === map.hours.length - 1 ? 'now' : i % 6 === 0 ? hourLabel(t) : ''))
	);
	// Stronger with more clips; a single clip is still clearly visible.
	const strength = (n: number) => Math.round(35 + 65 * Math.sqrt(n / Math.max(map.max, 1)));
</script>

<section class="card p-3 sm:p-4" aria-labelledby="heat-title">
	<div class="mb-3 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
		<h2 id="heat-title" class="text-sm font-semibold">Last 24 hours</h2>
		<p class="text-xs text-muted">
			{#if total}{total} {total === 1 ? 'clip' : 'clips'} · tap a square to see them{:else}No clips
				in the last 24 hours{/if}
		</p>
	</div>
	<div
		class="grid items-center gap-x-2 gap-y-1"
		style="grid-template-columns: minmax(0, max-content) minmax(0, 1fr)"
	>
		{#each map.rows as row (row.camera)}
			<div class="max-w-24 truncate text-xs text-muted sm:max-w-40" title={names[row.camera]}>
				{names[row.camera] ?? row.camera}
			</div>
			<div
				class="grid h-6 gap-[2px]"
				style="grid-template-columns: repeat({map.hours.length}, 1fr)"
			>
				{#each row.counts as n, i (i)}
					{@const label = `${names[row.camera] ?? row.camera}, ${hourLabel(map.hours[i])}: ${n} ${n === 1 ? 'clip' : 'clips'}`}
					{#if n}
						<button
							class="rounded-[3px] transition outline-none hover:ring-2 hover:ring-text/50 focus-visible:ring-2 focus-visible:ring-text"
							style="background: color-mix(in oklab, var(--accent) {strength(
								n
							)}%, var(--surface-2))"
							title={label}
							aria-label={label}
							onclick={() => onpick(row.camera, map.hours[i])}
						></button>
					{:else}
						<span class="rounded-[3px] bg-surface-2" title={label}></span>
					{/if}
				{/each}
			</div>
		{/each}
		<span></span>
		<div
			class="grid text-[10px] text-muted tabular-nums"
			style="grid-template-columns: repeat({map.hours.length}, 1fr)"
			aria-hidden="true"
		>
			{#each labels as label, i (i)}
				<span
					class="overflow-visible whitespace-nowrap {i === labels.length - 1
						? 'justify-self-end'
						: ''}">{label}</span
				>
			{/each}
		</div>
	</div>
</section>
