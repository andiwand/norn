<script lang="ts">
	// One numeric setting: label and hint on the left, the number with its unit on the right.
	let {
		label,
		hint = '',
		value = $bindable(),
		min = 0,
		max,
		step = 1,
		unit = '',
		fallback,
		placeholder
	}: {
		label: string;
		hint?: string;
		value: number | null | undefined;
		min?: number;
		max?: number;
		step?: number;
		unit?: string;
		/** The default, mentioned when the value differs from it. */
		fallback?: number;
		/** Shown when empty; with it the field may be left empty. */
		placeholder?: string;
	} = $props();

	const id = $props.id();
	const differs = $derived(fallback !== undefined && value !== null && fallback !== value);

	// A required field left empty gets its last number back (else the default): never sent empty.
	let last: number | undefined;
	$effect(() => {
		if (typeof value === 'number' && Number.isFinite(value)) last = value;
	});
	function onblur() {
		if (placeholder === undefined && (typeof value !== 'number' || !Number.isFinite(value)))
			value = last ?? fallback;
	}
</script>

<div class="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 px-5 py-3.5">
	<label for={id} class="min-w-0 flex-1 basis-56">
		<span class="block text-sm font-medium">{label}</span>
		{#if hint || differs}
			<span class="mt-0.5 block text-xs text-muted">
				{hint}{#if differs}
					{hint ? ' ' : ''}Default: {fallback}{unit ? ` ${unit}` : ''}.{/if}
			</span>
		{/if}
	</label>
	<div class="flex w-full shrink-0 justify-end sm:w-60">
		<span class="field w-44">
			<input
				{id}
				type="number"
				class="h-full w-full min-w-0 bg-transparent px-3 text-right tabular-nums outline-none placeholder:text-muted/60"
				bind:value
				{min}
				{max}
				{step}
				{placeholder}
				required={placeholder === undefined}
				{onblur}
			/>
			{#if unit}<span class="shrink-0 pr-3 text-muted">{unit}</span>{/if}
		</span>
	</div>
</div>
