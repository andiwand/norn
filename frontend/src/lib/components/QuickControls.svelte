<script lang="ts">
	// The switches people use every day, right under the video: those the driver gives an icon
	// (infrared, the status light, privacy, the camera's motion alarm, ...). All of them are also
	// in the Settings tab; buttons (a siren) are only there, out of reach of a stray tap.
	import type { Control } from '../api';
	import { controlIcon, isQuick } from '../control-icons';

	let {
		controls,
		onchange
	}: { controls: Control[]; onchange: (control: Control, value: unknown) => void } = $props();

	const quick = $derived(controls.filter(isQuick));
	const short = (c: Control) =>
		(c.options?.length ?? 0) <= 3 &&
		(c.options ?? []).reduce((n, o) => n + o.label.length, 0) <= 30;
</script>

{#if quick.length}
	<!-- Phones: one row that scrolls sideways; wider screens: as many rows as it takes. -->
	<div
		class="-mx-3 flex [scrollbar-width:none] gap-2 overflow-x-auto px-3 pb-1 sm:mx-0 sm:flex-wrap sm:overflow-visible sm:px-0"
		role="group"
		aria-label="Quick settings"
	>
		{#each quick as c (c.id)}
			{@const Icon = controlIcon(c.icon)}
			{#if c.kind === 'toggle'}
				<button
					role="switch"
					aria-checked={Boolean(c.value)}
					class="flex h-11 shrink-0 items-center gap-2.5 rounded-xl border px-3 text-sm font-medium transition {c.value
						? 'border-accent/40 bg-accent/12 text-text'
						: 'border-line bg-surface text-muted hover:text-text'}"
					onclick={() => onchange(c, !c.value)}
				>
					<Icon class="size-4 shrink-0 {c.value ? 'text-accent' : ''}" />
					<span class="whitespace-nowrap">{c.label}</span>
					<span
						class="relative h-5 w-9 shrink-0 rounded-full transition {c.value
							? 'bg-accent'
							: 'bg-surface-3'}"
						aria-hidden="true"
					>
						<span
							class="absolute top-0.5 left-0.5 size-4 rounded-full bg-white shadow transition {c.value
								? 'translate-x-4'
								: ''}"
						></span>
					</span>
				</button>
			{:else}
				<div
					class="flex h-11 shrink-0 items-center gap-2.5 rounded-xl border border-line bg-surface pr-1 pl-3"
					title={c.value == null ? 'Not known yet: Norn shows it once it is set here' : ''}
				>
					<Icon class="size-4 shrink-0 text-muted" />
					<span class="text-sm font-medium whitespace-nowrap">{c.label}</span>
					{#if short(c)}
						<div class="flex rounded-lg bg-surface-3 p-0.5" role="radiogroup" aria-label={c.label}>
							{#each c.options ?? [] as o (o.value)}
								<button
									role="radio"
									aria-checked={c.value === o.value}
									class="rounded-md px-2.5 py-1.5 text-xs font-medium whitespace-nowrap transition {c.value ===
									o.value
										? 'bg-surface text-text shadow'
										: 'text-muted hover:text-text'}"
									onclick={() => onchange(c, o.value)}>{o.label}</button
								>
							{/each}
						</div>
					{:else}
						<!-- More choices: a plain dropdown that belongs to the chip, not a field in it. -->
						<select
							class="h-9 min-w-0 cursor-pointer rounded-lg border-0 bg-surface-3 pr-7 pl-2.5 text-xs font-medium text-text outline-none focus-visible:ring-2 focus-visible:ring-accent"
							value={c.value ?? ''}
							aria-label={c.label}
							onchange={(e) => onchange(c, e.currentTarget.value)}
						>
							{#if c.value == null}<option value="" disabled>Choose…</option>{/if}
							{#each c.options ?? [] as o (o.value)}
								<option value={o.value}>{o.label}</option>
							{/each}
						</select>
					{/if}
				</div>
			{/if}
		{/each}
	</div>
{/if}
