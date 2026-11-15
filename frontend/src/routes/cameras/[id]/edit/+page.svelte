<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { api } from '#lib/api.js';
	import { store } from '#lib/state.svelte.js';
	import CameraForm from '#lib/components/CameraForm.svelte';
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';
	import Trash2 from '@lucide/svelte/icons/trash-2';

	const camera = $derived(store.camera(page.params.id ?? ''));
	let confirming = $state(false);

	async function remove() {
		if (!camera) return;
		const name = camera.name;
		try {
			await api.deleteCamera(camera.id);
		} catch (e) {
			store.toast(e instanceof Error ? e.message : String(e), 'error');
			return;
		}
		await store.refresh();
		store.toast(`${name} removed`, 'success');
		goto('/');
	}
</script>

<svelte:head><title>Edit {camera?.name ?? 'camera'} · Norn</title></svelte:head>

<div class="mx-auto max-w-2xl">
	<div class="mb-6 flex items-center gap-3">
		<a href="/cameras/{page.params.id}" class="-ml-2 icon-btn" aria-label="Back"
			><ArrowLeft class="size-5" /></a
		>
		<h1 class="text-xl font-semibold tracking-tight">Edit camera</h1>
	</div>

	{#if camera}
		{#key camera.id}
			<CameraForm {camera} onsaved={(c) => goto(`/cameras/${c.id}`)} />
		{/key}

		<section
			class="mt-10 flex flex-wrap items-center justify-between gap-4 card border-danger/25 p-5"
		>
			<div>
				<h2 class="text-sm font-semibold">Remove camera</h2>
				<p class="text-xs text-muted">Removes it from config.yaml. Its recordings stay on disk.</p>
			</div>
			{#if confirming}
				<div class="flex gap-2">
					<button class="btn-ghost" onclick={() => (confirming = false)}>Cancel</button>
					<button class="btn bg-danger text-white" onclick={remove}>Remove</button>
				</div>
			{:else}
				<button class="btn-danger" onclick={() => (confirming = true)}
					><Trash2 class="size-4" />Remove</button
				>
			{/if}
		</section>
	{:else if store.loaded}
		<p class="text-muted">There is no camera “{page.params.id}”.</p>
	{/if}
</div>
