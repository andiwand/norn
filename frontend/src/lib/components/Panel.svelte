<script lang="ts" module>
	// Which panels are open, by name, for all cameras: folding "Device" folds it everywhere.
	import { readStoredJson, writeStored } from '../stored';

	const KEY = 'norn.panels';
	const saved = readStoredJson<Record<string, boolean>>(KEY, {});
	function remember(name: string, open: boolean) {
		saved[name] = open;
		writeStored(KEY, JSON.stringify(saved));
	}
</script>

<script lang="ts">
	// A card that folds to its title line. Remembers whether it is open.
	import type { Snippet } from 'svelte';
	import { untrack } from 'svelte';
	import ChevronDown from '@lucide/svelte/icons/chevron-down';

	let {
		title,
		name = title,
		open: defaultOpen = false,
		summary,
		actions,
		children
	}: {
		title: string;
		/** The key it is remembered by. */
		name?: string;
		/** Open until someone folds or unfolds it. */
		open?: boolean;
		/** Shown in the title line while folded. */
		summary?: Snippet;
		/** Buttons in the title line. */
		actions?: Snippet;
		children: Snippet;
	} = $props();

	let open = $state(untrack(() => saved[name] ?? defaultOpen));
	const id = $props.id();

	function toggle() {
		open = !open;
		remember(name, open);
	}
</script>

<section class="card">
	<div class="flex items-center gap-2 pr-2">
		<h2 class="min-w-0 flex-1">
			<button
				class="flex w-full min-w-0 items-center gap-2 py-3.5 pl-4 text-left"
				aria-expanded={open}
				aria-controls={open ? id : undefined}
				onclick={toggle}
			>
				<ChevronDown
					class="size-4 shrink-0 text-muted transition-transform {open ? '' : '-rotate-90'}"
				/>
				<span class="shrink-0 eyebrow">{title}</span>
				{#if !open && summary}
					<span class="min-w-0 flex-1 truncate text-right text-xs text-muted"
						>{@render summary()}</span
					>
				{/if}
			</button>
		</h2>
		{#if open && actions}{@render actions()}{/if}
	</div>
	{#if open}
		<div {id} class="px-4 pb-4">{@render children()}</div>
	{/if}
</section>
