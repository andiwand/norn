<script lang="ts">
	// When detections may start recordings: time windows on days of the week. No windows: always.
	// With `inherit`, null means "as set above".
	import type { Window } from '../api';
	import Plus from '@lucide/svelte/icons/plus';
	import X from '@lucide/svelte/icons/x';

	let {
		label = 'When',
		hint = '',
		value = $bindable(),
		inherit,
		empty = 'Always.'
	}: {
		label?: string;
		hint?: string;
		value: Window[] | null;
		inherit?: Window[];
		/** What no windows mean, said when there are none. */
		empty?: string;
	} = $props();

	const DAYS = [
		['mon', 'Mo'],
		['tue', 'Tu'],
		['wed', 'We'],
		['thu', 'Th'],
		['fri', 'Fr'],
		['sat', 'Sa'],
		['sun', 'Su']
	] as const;
	const FULL: Record<string, string> = {
		mon: 'Monday',
		tue: 'Tuesday',
		wed: 'Wednesday',
		thu: 'Thursday',
		fri: 'Friday',
		sat: 'Saturday',
		sun: 'Sunday'
	};

	const own = $derived(value !== null);
	const windows = $derived(value ?? inherit ?? []);

	function describe(list: Window[]): string {
		if (!list.length) return 'always';
		return list
			.map((w) => {
				const days =
					w.days.length === 7
						? 'every day'
						: DAYS.filter(([d]) => w.days.includes(d))
								.map(([, l]) => l)
								.join(' ');
				return `${days} ${w.from}–${w.to}`;
			})
			.join(', ');
	}

	function editable(): Window[] {
		return value ?? structuredClone($state.snapshot(inherit ?? []));
	}
	function add() {
		value = [...editable(), { days: DAYS.map(([d]) => d), from: '20:00', to: '07:00' }];
	}
	function remove(i: number) {
		value = editable().filter((_, n) => n !== i);
	}
	function update(i: number, change: Partial<Window>) {
		value = editable().map((w, n) => (n === i ? { ...w, ...change } : w));
	}
	function toggleDay(i: number, day: string) {
		const w = editable()[i];
		const days = w.days.includes(day) ? w.days.filter((d) => d !== day) : [...w.days, day];
		if (days.length) update(i, { days: DAYS.map(([d]) => d).filter((d) => days.includes(d)) });
	}
</script>

<div class="px-5 py-3.5">
	<div class="flex flex-wrap items-center justify-between gap-x-6 gap-y-2">
		<div class="min-w-0 flex-1 basis-56">
			<span class="block text-sm font-medium">{label}</span>
			<span class="mt-0.5 block text-xs text-muted">
				{hint}
				{#if inherit !== undefined && !own}As set above: {describe(
						windows
					)}.{:else if !windows.length}{empty}{/if}
			</span>
		</div>
		<div class="flex shrink-0 items-center gap-2">
			{#if inherit !== undefined && own}
				<button type="button" class="chip border-dashed" onclick={() => (value = null)}
					>Default</button
				>
			{/if}
			<button type="button" class="chip" onclick={add}><Plus class="size-3.5" />Time window</button>
		</div>
	</div>
	{#if own || inherit === undefined}
		{#each windows as w, i (i)}
			<div class="mt-2 flex flex-wrap items-center gap-2 rounded-xl bg-surface-2/60 p-2">
				<div class="flex flex-wrap gap-1" role="group" aria-label="Days">
					{#each DAYS as [day, short] (day)}
						<button
							type="button"
							role="switch"
							aria-checked={w.days.includes(day)}
							aria-label={FULL[day]}
							class="grid size-7 place-items-center rounded-lg text-[11px] font-semibold transition {w.days.includes(
								day
							)
								? 'bg-accent text-accent-ink'
								: 'bg-surface-3 text-muted hover:text-text'}"
							onclick={() => toggleDay(i, day)}>{short}</button
						>
					{/each}
				</div>
				<span class="ml-auto flex items-center gap-1.5 text-sm">
					<input
						type="time"
						class="field h-8 px-2 tabular-nums"
						value={w.from}
						aria-label="From"
						onchange={(e) =>
							e.currentTarget.value
								? update(i, { from: e.currentTarget.value })
								: (e.currentTarget.value = w.from)}
					/>
					<span class="text-muted">to</span>
					<input
						type="time"
						class="field h-8 px-2 tabular-nums"
						value={w.to}
						aria-label="To"
						onchange={(e) =>
							e.currentTarget.value
								? update(i, { to: e.currentTarget.value })
								: (e.currentTarget.value = w.to)}
					/>
					<button
						type="button"
						class="icon-btn size-8"
						aria-label="Remove"
						onclick={() => remove(i)}><X class="size-4" /></button
					>
				</span>
				{#if w.to <= w.from}
					<span class="w-full px-1 text-[11px] text-muted"
						>Runs past midnight into the next day.</span
					>
				{/if}
			</div>
		{/each}
	{/if}
</div>
