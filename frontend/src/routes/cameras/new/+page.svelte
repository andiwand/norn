<script lang="ts">
	import { goto } from '$app/navigation';
	import CameraForm from '#lib/components/CameraForm.svelte';
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';
</script>

<svelte:head><title>Add camera · Norn</title></svelte:head>

<div class="mx-auto max-w-2xl">
	<div class="mb-6 flex items-center gap-3">
		<a href="/" class="-ml-2 icon-btn" aria-label="Back"><ArrowLeft class="size-5" /></a>
		<h1 class="text-xl font-semibold tracking-tight">Add camera</h1>
	</div>
	<CameraForm onsaved={(c) => goto(`/cameras/${c.id}`)} />
</div>
