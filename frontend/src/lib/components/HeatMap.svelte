<script lang="ts">
	// Clips per camera over the last day, 3 days or week: the shape of the time at a glance. A
	// square with clips jumps to the event they belong to. The period, as everywhere, at the
	// right end of the header.
	import type { HeatMap } from '../events';
	import { RECENT, recentText, type RecentDays } from '../periods';
	import PeriodPicker from './PeriodPicker.svelte';

	let {
		map,
		names,
		days,
		onpick,
		ondays
	}: {
		map: HeatMap;
		names: Record<string, string>;
		days: RecentDays;
		/** A square with clips: its camera, and when it starts and ends. */
		onpick: (camera: string, start: number, end: number) => void;
		ondays: (days: RecentDays) => void;
	} = $props();

	const time = (t: number) =>
		new Date(t).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
	// A square's own name: its time over a day, its day and time over more.
	const squareName = (t: number) =>
		days === 1
			? time(t)
			: new Date(t).toLocaleString([], { weekday: 'short', hour: '2-digit', minute: '2-digit' });
	const total = $derived(map.rows.reduce((sum, r) => sum + r.counts.reduce((a, b) => a + b, 0), 0));
	// Over a day, a label every 6 hours; over days, each day where it begins. "now" at the end.
	const labels = $derived(
		map.starts.map((t, i) => {
			if (i === map.starts.length - 1) return 'now';
			if (days === 1) return new Date(t).getHours() % 6 === 0 ? time(t) : '';
			const d = new Date(t);
			return d.getHours() === 0 && i < map.starts.length - 2
				? d.toLocaleDateString([], { weekday: 'short', day: 'numeric' })
				: '';
		})
	);
	// Stronger with more clips; a single clip is still clearly visible.
	const strength = (n: number) => Math.round(35 + 65 * Math.sqrt(n / Math.max(map.max, 1)));
</script>

<section class="card p-3 sm:p-5" aria-labelledby="heat-title">
	<div class="mb-3 flex flex-wrap items-center gap-2">
		<h2 id="heat-title" class="min-w-0 text-sm font-semibold">
			{total}
			{total === 1 ? 'clip' : 'clips'}
		</h2>
		<span class="min-w-0 truncate text-xs text-muted">
			{`in ${recentText(days)}`}{#if total}<span class="hidden sm:inline"
					>{' · tap a square to see them'}</span
				>{/if}
		</span>
		<div class="ml-auto"><PeriodPicker options={RECENT} value={days} onpick={ondays} /></div>
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
				style="grid-template-columns: repeat({map.starts.length}, 1fr)"
			>
				{#each row.counts as n, i (i)}
					{@const label = `${names[row.camera] ?? row.camera}, ${squareName(map.starts[i])}: ${n} ${n === 1 ? 'clip' : 'clips'}`}
					{#if n}
						<button
							class="rounded-[3px] transition outline-none hover:ring-2 hover:ring-text/50 focus-visible:ring-2 focus-visible:ring-text"
							style="background: color-mix(in oklab, var(--accent) {strength(
								n
							)}%, var(--surface-2))"
							title={label}
							aria-label={label}
							onclick={() => onpick(row.camera, map.starts[i], map.starts[i + 1] ?? map.end)}
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
			style="grid-template-columns: repeat({map.starts.length}, 1fr)"
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
