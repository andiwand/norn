<script lang="ts">
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { api, type Recording } from '#lib/api.js';
	import { store } from '#lib/state.svelte.js';
	import { formatDay } from '#lib/format.js';
	import RecordingTile from '#lib/components/RecordingTile.svelte';
	import RecordingDialog from '#lib/components/RecordingDialog.svelte';
	import Film from '@lucide/svelte/icons/film';

	const camera = $derived(page.url.searchParams.get('camera') ?? '');
	const trigger = $derived(page.url.searchParams.get('trigger') ?? '');

	let recordings = $state<Recording[]>([]);
	let loading = $state(true);
	let open = $state<Recording | null>(null);

	async function load(cameraId: string) {
		loading = true;
		const data = await api
			.recordings({ camera: cameraId || undefined, limit: 1000 })
			.catch(() => null);
		recordings = data?.recordings ?? [];
		loading = false;
	}

	$effect(() => {
		const cameraId = camera;
		load(cameraId);
		return store.on((e) => {
			if (e.type === 'recording.finished' || e.type === 'recording.deleted') load(cameraId);
		});
	});

	const filtered = $derived(
		recordings.filter(
			(r) => !trigger || (trigger === 'clips' ? r.trigger !== 'continuous' : r.trigger === trigger)
		)
	);
	const byDay = $derived(
		Object.entries(
			filtered.reduce<Record<string, Recording[]>>((acc, r) => {
				(acc[r.day] ??= []).push(r);
				return acc;
			}, {})
		)
	);

	function setFilter(key: string, value: string) {
		const url = new URL(page.url.href);
		if (value) url.searchParams.set(key, value);
		else url.searchParams.delete(key);
		goto(url, { replaceState: true });
	}
</script>

<svelte:head><title>Recordings · Norn</title></svelte:head>

<div class="mb-6">
	<h1 class="text-2xl font-semibold tracking-tight">Recordings</h1>
	<p class="mt-1 text-sm text-muted">Stored as plain MP4 files in the recordings folder.</p>
</div>

<div class="mb-6 flex flex-wrap gap-2">
	<button class="chip {camera === '' ? 'chip-active' : ''}" onclick={() => setFilter('camera', '')}
		>All cameras</button
	>
	{#each store.cameras as c (c.id)}
		<button
			class="chip {camera === c.id ? 'chip-active' : ''}"
			onclick={() => setFilter('camera', c.id)}>{c.name}</button
		>
	{/each}
	<span class="mx-1 w-px self-stretch bg-line"></span>
	<button
		class="chip {trigger === '' ? 'chip-active' : ''}"
		onclick={() => setFilter('trigger', '')}>Everything</button
	>
	<button
		class="chip {trigger === 'clips' ? 'chip-active' : ''}"
		onclick={() => setFilter('trigger', 'clips')}>Clips</button
	>
	<button
		class="chip {trigger === 'continuous' ? 'chip-active' : ''}"
		onclick={() => setFilter('trigger', 'continuous')}
	>
		Continuous
	</button>
</div>

{#if loading && !recordings.length}
	<div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 2xl:grid-cols-6">
		{#each Array(8) as _, i (i)}
			<div class="aspect-[4/3] animate-pulse rounded-2xl bg-surface-2"></div>
		{/each}
	</div>
{:else if !filtered.length}
	<div class="mx-auto mt-10 flex max-w-md flex-col items-center card px-8 py-14 text-center">
		<span class="mb-5 grid size-14 place-items-center rounded-2xl bg-accent/15 text-accent"
			><Film class="size-7" /></span
		>
		<h2 class="text-lg font-semibold">Nothing recorded yet</h2>
		<p class="mt-2 text-sm text-muted">
			Record a clip from a camera's page, call the record webhook, or turn on continuous recording
			for a camera.
		</p>
	</div>
{:else}
	<div class="space-y-8">
		{#each byDay as [day, items] (day)}
			<section>
				<h2 class="mb-3 flex items-baseline gap-2">
					<span class="text-base font-semibold">{formatDay(day)}</span>
					<span class="text-xs text-muted">{items.length}</span>
				</h2>
				<div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 2xl:grid-cols-6">
					{#each items as r (r.id)}
						<RecordingTile
							recording={r}
							cameraName={store.camera(r.camera)?.name}
							onopen={(x) => (open = x)}
						/>
					{/each}
				</div>
			</section>
		{/each}
	</div>
{/if}

<RecordingDialog
	bind:recording={open}
	ondeleted={(r) => (recordings = recordings.filter((x) => x.id !== r.id))}
/>
