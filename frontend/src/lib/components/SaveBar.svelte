<script lang="ts">
	// The headline of a settings page, with Save and Discard beside it and the page's tabs (if
	// it has any). It stays below the top bar while scrolling; once it sticks, a line sets it off.
	import type { Snippet } from 'svelte';

	let {
		title,
		dirty,
		saving,
		onsave,
		ondiscard,
		saves = true,
		children
	}: {
		title: string;
		dirty: boolean;
		saving: boolean;
		onsave: () => void;
		ondiscard: () => void;
		/** Whether this tab has things to save (a tab that acts at once has no Save). */
		saves?: boolean;
		children?: Snippet;
	} = $props();

	// Stuck: scrolled, and the bar sits at its place below the top bar.
	let bar = $state<HTMLElement>();
	let stuck = $state(false);
	$effect(() => {
		if (!bar) return;
		const el = bar;
		const check = () => {
			const top = parseFloat(getComputedStyle(el).top) || 0;
			stuck = scrollY > 0 && el.getBoundingClientRect().top <= top + 0.5;
		};
		check();
		addEventListener('scroll', check, { passive: true });
		addEventListener('resize', check);
		return () => {
			removeEventListener('scroll', check);
			removeEventListener('resize', check);
		};
	});
</script>

<div
	bind:this={bar}
	class="sticky top-12 z-20 -mx-3 flex flex-wrap items-center gap-x-3 gap-y-2 px-3 py-2 transition-[background-color,border-color] sm:-mx-6 sm:px-6 md:top-14 {stuck
		? 'border-b border-line bg-bg/95 backdrop-blur-xl'
		: 'border-b border-transparent'}"
>
	<h1 class="min-w-0 truncate page-title">{title}</h1>
	{#if children}
		<!-- On a phone the tabs get a row of their own. -->
		<div class="order-last w-full sm:order-none sm:w-auto">{@render children()}</div>
	{/if}
	<span
		class="ml-auto flex shrink-0 items-center gap-2 {saves ? '' : 'invisible'}"
		aria-hidden={!saves}
	>
		<span class="hidden text-xs sm:inline {dirty ? 'font-medium text-accent' : 'text-muted'}">
			{dirty ? 'Unsaved changes' : 'All saved'}
		</span>
		{#if dirty}
			<button type="button" class="btn-ghost h-9" onclick={ondiscard}>Discard</button>
		{/if}
		<button type="button" class="btn-primary h-9" disabled={!dirty || saving} onclick={onsave}>
			{saving ? 'Saving…' : 'Save'}
		</button>
	</span>
</div>
