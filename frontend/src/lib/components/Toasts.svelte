<script lang="ts">
	import { store } from '../state.svelte';
	import { fly } from 'svelte/transition';
	import CircleCheck from '@lucide/svelte/icons/circle-check';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import Info from '@lucide/svelte/icons/info';
	import X from '@lucide/svelte/icons/x';
</script>

<div
	class="pointer-events-none fixed inset-x-0 bottom-20 z-50 flex flex-col items-center gap-2 px-4 md:bottom-6"
	aria-live="polite"
>
	{#each store.toasts as toast (toast.id)}
		<div
			transition:fly={{ y: 16, duration: 200 }}
			class="pointer-events-auto flex w-full max-w-md items-start gap-3 card bg-surface-2/95 px-4 py-3 text-sm shadow-2xl"
		>
			{#if toast.kind === 'success'}
				<CircleCheck class="mt-0.5 size-4 shrink-0 text-success" />
			{:else if toast.kind === 'error'}
				<TriangleAlert class="mt-0.5 size-4 shrink-0 text-danger" />
			{:else}
				<Info class="mt-0.5 size-4 shrink-0 text-accent" />
			{/if}
			<p class="flex-1 break-words">{toast.message}</p>
			<button
				class="-m-1 p-1 text-muted hover:text-text"
				onclick={() => store.dismiss(toast.id)}
				aria-label="Dismiss"
			>
				<X class="size-4" />
			</button>
		</div>
	{/each}
</div>
