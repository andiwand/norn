<script lang="ts">
	// One camera setting, drawn from the driver's description of it.
	import type { Component } from 'svelte';
	import type { Control } from '../api';
	import Moon from '@lucide/svelte/icons/moon';
	import Sun from '@lucide/svelte/icons/sun';
	import Lamp from '@lucide/svelte/icons/lamp';
	import Siren from '@lucide/svelte/icons/siren';
	import Activity from '@lucide/svelte/icons/activity';
	import EyeOff from '@lucide/svelte/icons/eye-off';
	import Bell from '@lucide/svelte/icons/bell';
	import Volume2 from '@lucide/svelte/icons/volume-2';
	import Settings2 from '@lucide/svelte/icons/settings-2';

	let {
		control,
		mixed = false,
		onchange
	}: {
		control: Control;
		/** Cameras of a circle disagree: show no value rather than a made-up one. */
		mixed?: boolean;
		onchange: (value: unknown) => void;
	} = $props();

	const icons: Record<string, Component> = {
		moon: Moon,
		sun: Sun,
		lamp: Lamp,
		siren: Siren,
		activity: Activity,
		'eye-off': EyeOff,
		bell: Bell,
		volume: Volume2
	};
	const Icon = $derived(icons[control.icon ?? ''] ?? Settings2);

	// The slider shows its value while dragging and sends it once on release.
	let draft = $state<number | null>(null);
	const rangeValue = $derived(draft ?? Number(control.value ?? control.min ?? 0));

	// Few short choices fit as buttons next to the label; more get a dropdown, so nothing overflows.
	const segmented = $derived(
		(control.options?.length ?? 0) <= 3 &&
			(control.options ?? []).reduce((n, o) => n + o.label.length, 0) <= 16
	);
</script>

<div class="flex min-h-12 items-center gap-3">
	<span class="grid size-9 shrink-0 place-items-center rounded-xl bg-surface-3 text-muted">
		<Icon class="size-4" />
	</span>

	{#if control.kind === 'toggle'}
		<label class="flex flex-1 cursor-pointer items-center justify-between gap-3">
			<span class="text-sm font-medium">{control.label}</span>
			<input
				type="checkbox"
				role="switch"
				class="peer sr-only"
				checked={Boolean(control.value)}
				indeterminate={mixed}
				onchange={(e) => onchange(e.currentTarget.checked)}
			/>
			<span
				class="relative h-6 w-11 shrink-0 rounded-full bg-surface-3 transition peer-checked:bg-accent peer-focus-visible:ring-2 peer-focus-visible:ring-accent after:absolute after:top-0.5 after:left-0.5 after:size-5 after:rounded-full after:bg-white after:shadow after:transition peer-checked:after:translate-x-5"
				aria-hidden="true"
			></span>
		</label>
	{:else if control.kind === 'select' && !segmented}
		<label class="flex min-w-0 flex-1 items-center justify-between gap-3">
			<span class="text-sm font-medium">{control.label}</span>
			<select
				class="input h-9 w-auto max-w-[60%] min-w-0 pr-8 text-xs font-medium"
				value={mixed ? '' : control.value}
				onchange={(e) => onchange(e.currentTarget.value)}
			>
				{#if mixed}<option value="" disabled>Mixed</option>{/if}
				{#each control.options ?? [] as option (option.value)}
					<option value={option.value}>{option.label}</option>
				{/each}
			</select>
		</label>
	{:else if control.kind === 'select'}
		<span class="min-w-0 flex-1 text-sm font-medium">{control.label}</span>
		<div
			class="flex shrink-0 rounded-xl bg-surface-3 p-1"
			role="radiogroup"
			aria-label={control.label}
		>
			{#each control.options ?? [] as option (option.value)}
				<button
					role="radio"
					aria-checked={control.value === option.value}
					class="rounded-lg px-2.5 py-1.5 text-xs font-medium whitespace-nowrap transition {control.value ===
					option.value
						? 'bg-surface text-text shadow'
						: 'text-muted hover:text-text'}"
					onclick={() => onchange(option.value)}
				>
					{option.label}
				</button>
			{/each}
		</div>
	{:else if control.kind === 'range'}
		<div class="flex-1">
			<div class="mb-1 flex justify-between text-sm">
				<span class="font-medium">{control.label}</span>
				<span class="text-muted tabular-nums">{rangeValue}{control.unit ?? ''}</span>
			</div>
			<input
				type="range"
				class="w-full accent-[var(--accent)]"
				min={control.min}
				max={control.max}
				step={control.step}
				value={rangeValue}
				aria-label={control.label}
				oninput={(e) => (draft = Number(e.currentTarget.value))}
				onchange={(e) => {
					onchange(Number(e.currentTarget.value));
					draft = null;
				}}
			/>
		</div>
	{:else}
		<span class="flex-1 text-sm font-medium">{control.label}</span>
		<button class="btn-ghost h-9" onclick={() => onchange(null)}>Trigger</button>
	{/if}
</div>
