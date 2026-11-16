<script lang="ts">
	import { goto } from '$app/navigation';
	import CircleForm from '#lib/components/CircleForm.svelte';
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';
</script>

<svelte:head><title>New circle · Norn</title></svelte:head>

<div class="mx-auto max-w-2xl">
	<div class="mb-6 flex items-center gap-3">
		<a href="/" class="-ml-2 icon-btn" aria-label="Back"><ArrowLeft class="size-5" /></a>
		<div>
			<h1 class="text-xl font-semibold tracking-tight">New circle</h1>
			<p class="text-xs text-muted">
				A group of cameras: record them together, give them settings, set what they share at once.
			</p>
		</div>
	</div>
	<CircleForm onsaved={(c) => goto(`/circles/${c.id}`)} />
</div>
