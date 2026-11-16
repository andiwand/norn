<script lang="ts">
	// A card of settings: a title, a few words on what it is about, and its rows.
	import type { Component, Snippet } from 'svelte';

	let {
		title,
		description = '',
		icon: Icon,
		aside,
		children
	}: {
		title: string;
		description?: string;
		icon?: Component;
		/** Shown at the right of the title. */
		aside?: Snippet;
		children: Snippet;
	} = $props();
</script>

<section class="overflow-hidden card">
	<header class="border-b border-line px-5 pt-5 pb-4">
		<div class="flex items-center gap-2">
			{#if Icon}<Icon class="size-4 text-muted" />{/if}
			<h2 class="text-base font-semibold">{title}</h2>
			{#if aside}<span class="ml-auto">{@render aside()}</span>{/if}
		</div>
		{#if description}<p class="mt-1.5 max-w-prose text-sm text-muted">{description}</p>{/if}
	</header>
	<div class="divide-y divide-line">{@render children()}</div>
</section>
