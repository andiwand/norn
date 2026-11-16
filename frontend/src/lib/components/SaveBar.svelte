<script lang="ts">
	// Save and Discard at the top of a settings page, in sight while scrolling, beside the page's
	// tabs (if it has any).
	import type { Snippet } from 'svelte';

	let {
		dirty,
		saving,
		onsave,
		ondiscard,
		children
	}: {
		dirty: boolean;
		saving: boolean;
		onsave: () => void;
		ondiscard: () => void;
		children?: Snippet;
	} = $props();
</script>

<div
	class="sticky top-16 z-20 -mx-4 flex flex-wrap items-center gap-2 border-b border-line bg-bg/85 px-4 py-2.5 backdrop-blur-xl sm:mx-0 sm:rounded-2xl sm:border sm:px-2 {dirty
		? 'sm:border-accent/50'
		: ''}"
>
	{#if children}{@render children()}{/if}
	<span class="ml-auto flex items-center gap-2">
		<span class="text-xs {dirty ? 'font-medium text-accent' : 'text-muted'}">
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
