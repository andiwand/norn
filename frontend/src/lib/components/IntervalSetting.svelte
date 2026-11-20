<script lang="ts">
	// How often something happens, in seconds: off (0), or every N seconds/minutes/hours.
	// With `inherit`, null means "as set above" (the global or circle value, `inherit` seconds).
	import { shortInterval } from '../format';

	let {
		label,
		hint = '',
		value = $bindable(),
		inherit,
		min = 10,
		max = 86400
	}: {
		label: string;
		hint?: string;
		value: number | null;
		inherit?: number;
		min?: number;
		max?: number;
	} = $props();

	const id = $props.id();
	const UNITS = [
		['sec', 1],
		['min', 60],
		['hours', 3600]
	] as const;

	type Mode = 'inherit' | 'off' | 'on';
	const mode = $derived<Mode>(value === null ? 'inherit' : value === 0 ? 'off' : 'on');

	// The unit that shows the value as a whole number, largest first.
	function unitOf(seconds: number): number {
		for (const [, size] of [...UNITS].reverse()) if (seconds % size === 0) return size;
		return 1;
	}
	let unit = $state(60);
	let amount = $state(5);
	$effect.pre(() => {
		if (value) {
			unit = unitOf(value);
			amount = value / unit;
		}
	});

	function setMode(next: Mode) {
		if (next === 'inherit') value = null;
		else if (next === 'off') value = 0;
		else value = clamp(amount * unit || 300);
	}
	const clamp = (seconds: number) => Math.min(max, Math.max(min, Math.round(seconds)));
	function setAmount(input: HTMLInputElement | null, n: number, size: number) {
		if (!Number.isFinite(n) || n <= 0) {
			if (input) input.value = String(amount); // nothing saved: show what is
			return;
		}
		value = clamp(n * size);
	}
</script>

<div class="@container flex flex-wrap items-center justify-between gap-x-6 gap-y-2 px-5 py-3.5">
	<label for={inherit === undefined ? id : `${id}-amount`} class="min-w-0 flex-1 basis-56">
		<span class="block text-sm font-medium">{label}</span>
		<span class="mt-0.5 block text-xs text-muted">
			{#if hint}{hint}{/if}
		</span>
	</label>
	<div class="flex w-full shrink-0 flex-col items-end gap-2 @[33rem]:w-60">
		{#if inherit !== undefined}
			<!-- Three ways: as above, off, or its own interval. -->
			<div class="flex rounded-xl bg-surface-3 p-1" role="radiogroup" aria-label={label}>
				{#each [['inherit', `Default (${shortInterval(inherit)})`], ['off', 'Off'], ['on', 'Own']] as const as [m, text] (m)}
					<button
						type="button"
						role="radio"
						aria-checked={mode === m}
						class="rounded-lg px-2.5 py-1 text-xs font-medium whitespace-nowrap transition {mode ===
						m
							? 'bg-surface text-text shadow'
							: 'text-muted hover:text-text'}"
						onclick={() => setMode(m)}>{text}</button
					>
				{/each}
			</div>
		{/if}
		<div class="flex items-center gap-3">
			{#if inherit === undefined}
				<input
					{id}
					type="checkbox"
					role="switch"
					class="switch"
					checked={mode === 'on'}
					onchange={(e) => setMode(e.currentTarget.checked ? 'on' : 'off')}
					aria-label="{label}: on"
				/>
			{/if}
			{#if mode === 'on' || inherit === undefined}
				<span class="field w-44 {mode === 'on' ? '' : 'pointer-events-none opacity-40'}">
					<span class="shrink-0 pl-3 text-muted">every</span>
					<input
						id="{id}-amount"
						type="number"
						class="h-full w-full min-w-0 bg-transparent px-2 text-right tabular-nums outline-none"
						min="1"
						value={amount}
						disabled={mode !== 'on'}
						aria-label="{label}: how many"
						onchange={(e) => setAmount(e.currentTarget, e.currentTarget.valueAsNumber, unit)}
					/>
					<select
						class="h-full shrink-0 cursor-pointer border-l border-line bg-transparent pr-2 pl-2 text-muted outline-none"
						value={unit}
						disabled={mode !== 'on'}
						aria-label="{label}: unit"
						onchange={(e) => setAmount(null, amount, Number(e.currentTarget.value))}
					>
						{#each UNITS as [name, size] (size)}
							<option value={size}>{name}</option>
						{/each}
					</select>
				</span>
			{/if}
		</div>
	</div>
</div>
