<script lang="ts">
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { api, type Recording } from '#lib/api.js';
	import { store } from '#lib/state.svelte.js';
	import { formatDay } from '#lib/format.js';
	import RecordingTile from '#lib/components/RecordingTile.svelte';
	import RecordingDialog from '#lib/components/RecordingDialog.svelte';
	import StorageStages from '#lib/components/StorageStages.svelte';
	import Timeline from '#lib/components/Timeline.svelte';
	import LayoutGrid from '@lucide/svelte/icons/layout-grid';
	import ChartGantt from '@lucide/svelte/icons/chart-gantt';
	import Film from '@lucide/svelte/icons/film';

	const camera = $derived(page.url.searchParams.get('camera') ?? '');
	const trigger = $derived(page.url.searchParams.get('trigger') ?? '');
	// The timeline is the default; the grid is one click away.
	const view = $derived(page.url.searchParams.get('view') === 'grid' ? 'grid' : 'timeline');
	let at = $state(0);

	const LIMIT = 1000;
	let recordings = $state<Recording[]>([]);
	let truncated = $state(false);
	let loading = $state(true);
	let open = $state<Recording | null>(null);

	// The server filters, so a flood of pictures can't push the clips out of the newest LIMIT.
	let sequence = 0;
	async function load(cameraId: string, filter: string) {
		const mine = ++sequence;
		loading = true;
		const data = await api
			.recordings({
				camera: cameraId || undefined,
				limit: LIMIT,
				kind: filter === 'pictures' ? 'picture' : undefined,
				trigger: filter && filter !== 'pictures' ? filter : undefined
			})
			.catch(() => null);
		if (mine !== sequence) return; // the filter changed meanwhile
		recordings = data?.recordings ?? [];
		truncated = data?.truncated ?? false;
		loading = false;
	}

	// Only the grid loads here; the timeline loads its own window.
	$effect(() => {
		if (view !== 'grid') return;
		const cameraId = camera;
		const filter = trigger;
		load(cameraId, filter);
		// Pictures can come every few seconds: reload at most every 10 seconds.
		let timer: ReturnType<typeof setTimeout> | undefined;
		const off = store.on((e) => {
			if (!['recording.finished', 'recording.deleted', 'recording.picture'].includes(e.type))
				return;
			timer ??= setTimeout(() => {
				timer = undefined;
				load(cameraId, filter);
			}, 10_000);
		});
		return () => {
			off();
			clearTimeout(timer);
		};
	});

	// The lifetime rings count down.
	let now = $state(Date.now());
	$effect(() => {
		const timer = setInterval(() => (now = Date.now()), 60_000);
		return () => clearInterval(timer);
	});

	const filtered = $derived(recordings);
	const byDay = $derived(
		Object.entries(
			filtered.reduce<Record<string, Recording[]>>((acc, r) => {
				(acc[r.day] ??= []).push(r);
				return acc;
			}, {})
		)
	);

	async function pin(r: Recording, pinned: boolean) {
		const updated = await store.pin(r, pinned);
		if (updated) replace(updated);
	}

	function replace(updated: Recording) {
		recordings = recordings.map((x) => (x.id === updated.id ? updated : x));
	}

	async function remove(r: Recording) {
		const ok = await store.attempt(async () => {
			await api.deleteRecording(r.id);
			return true;
		}, 'Recording deleted');
		if (ok) recordings = recordings.filter((x) => x.id !== r.id);
	}

	function setFilter(key: string, value: string) {
		const url = new URL(page.url.href);
		if (value) url.searchParams.set(key, value);
		else url.searchParams.delete(key);
		goto(url, { replaceState: true });
	}
</script>

<svelte:head><title>Recordings · Norn</title></svelte:head>

<div class="mb-6 flex flex-wrap items-start gap-4">
	<div class="min-w-0 flex-1 basis-80">
		<h1 class="text-2xl font-semibold tracking-tight">Recordings</h1>
		<p class="mt-1 text-sm text-muted">
			Plain MP4 and JPEG files in the recordings folder. The ring on a recording shows how long
			until Norn deletes it; clips you record by hand stay.
		</p>
	</div>
	<div class="flex rounded-xl bg-surface-3 p-1" role="radiogroup" aria-label="View">
		{#each [{ id: 'timeline', label: 'Timeline', icon: ChartGantt }, { id: 'grid', label: 'Grid', icon: LayoutGrid }] as v (v.id)}
			<button
				role="radio"
				aria-checked={view === v.id}
				class="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition {view ===
				v.id
					? 'bg-surface text-text shadow'
					: 'text-muted hover:text-text'}"
				onclick={() => setFilter('view', v.id === 'timeline' ? '' : v.id)}
				><v.icon class="size-4" />{v.label}</button
			>
		{/each}
	</div>
</div>

<div class="mb-6"><StorageStages compact /></div>

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
	{#if view === 'grid'}
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
		<button
			class="chip {trigger === 'pictures' ? 'chip-active' : ''}"
			onclick={() => setFilter('trigger', 'pictures')}>Pictures</button
		>
	{/if}
</div>

{#if view === 'timeline'}
	<Timeline
		cameras={camera ? store.cameras.filter((c) => c.id === camera) : store.cameras}
		onopen={(r, seconds) => {
			at = seconds;
			open = r;
		}}
	/>
{:else if loading && !recordings.length}
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
		{#if truncated}
			<p class="rounded-xl bg-warning/10 px-4 py-3 text-sm text-warning">
				Showing the newest {LIMIT}. Pick a camera or a kind above, or use the timeline, to see older
				ones.
			</p>
		{/if}
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
							onopen={(x) => {
								at = 0;
								open = x;
							}}
							ondelete={remove}
							onpin={pin}
							{now}
						/>
					{/each}
				</div>
			</section>
		{/each}
	</div>
{/if}

<RecordingDialog
	bind:recording={open}
	onchanged={replace}
	{at}
	ondeleted={(r) => (recordings = recordings.filter((x) => x.id !== r.id))}
/>
