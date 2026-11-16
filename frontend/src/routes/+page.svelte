<script lang="ts">
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { store } from '#lib/state.svelte.js';
	import Settings2 from '@lucide/svelte/icons/settings-2';
	import CameraTile from '#lib/components/CameraTile.svelte';
	import Plus from '@lucide/svelte/icons/plus';
	import Cctv from '@lucide/svelte/icons/cctv';
	import Columns2 from '@lucide/svelte/icons/columns-2';
	import LayoutGrid from '@lucide/svelte/icons/layout-grid';
	import Grid3x3 from '@lucide/svelte/icons/grid-3x3';

	type Density = 1 | 2 | 3;
	let density = $state<Density>(loadDensity());

	function loadDensity(): Density {
		try {
			const value = Number(localStorage.getItem('norn.density'));
			return value === 1 || value === 2 || value === 3 ? value : 2;
		} catch {
			return 2;
		}
	}
	function setDensity(value: Density) {
		density = value;
		try {
			localStorage.setItem('norn.density', String(value));
		} catch {
			// private mode
		}
	}

	const columns: Record<Density, string> = {
		1: 'grid-cols-1 max-w-5xl mx-auto',
		2: 'grid-cols-1 md:grid-cols-2',
		3: 'grid-cols-1 sm:grid-cols-2 xl:grid-cols-3'
	};
	const recording = $derived(store.cameras.filter((c) => c.recording).length);

	// A circle shows only its cameras.
	const circleId = $derived(page.url.searchParams.get('circle') ?? '');
	const circle = $derived(store.circle(circleId));
	const shown = $derived(
		circle ? store.cameras.filter((c) => circle.cameras.includes(c.id)) : store.cameras
	);

	function showCircle(id: string) {
		goto(id ? `/?circle=${encodeURIComponent(id)}` : '/', { replaceState: true });
	}
</script>

<svelte:head><title>Live · Norn</title></svelte:head>

<div class="mb-6 flex flex-wrap items-end justify-between gap-4">
	<div>
		<h1 class="text-2xl font-semibold tracking-tight">Live</h1>
		<p class="mt-1 text-sm text-muted">
			{store.cameras.length}
			{store.cameras.length === 1 ? 'camera' : 'cameras'}{#if recording}<span>
					· {recording} recording</span
				>{/if}
		</p>
	</div>
	<div class="flex items-center gap-2">
		<div
			class="hidden rounded-xl border border-line bg-surface-2/70 p-1 sm:flex"
			role="radiogroup"
			aria-label="Layout"
		>
			{#each [[1, Columns2], [2, LayoutGrid], [3, Grid3x3]] as const as [value, Icon] (value)}
				<button
					class="grid size-8 place-items-center rounded-lg transition {density === value
						? 'bg-surface-3 text-text'
						: 'text-muted hover:text-text'}"
					role="radio"
					aria-checked={density === value}
					aria-label="{value} per row"
					onclick={() => setDensity(value)}
				>
					<Icon class="size-4" />
				</button>
			{/each}
		</div>
		<a href="/cameras/new" class="btn-primary"><Plus class="size-4" />Add camera</a>
	</div>
</div>

{#if store.cameras.length}
	<div class="mb-5 flex flex-wrap items-center gap-2">
		<button class="chip {!circle ? 'chip-active' : ''}" onclick={() => showCircle('')}
			>All cameras</button
		>
		{#each store.circles as c (c.id)}
			<button
				class="chip {circle?.id === c.id ? 'chip-active' : ''}"
				onclick={() => showCircle(c.id)}
				>{c.name}<span class="text-muted/70">{c.cameras.length}</span></button
			>
		{/each}
		{#if circle}
			<a href="/circles/{circle.id}" class="chip"><Settings2 class="size-3.5" />Record, settings</a>
		{/if}
		<a href="/circles/new" class="chip border-dashed"><Plus class="size-3.5" />Circle</a>
	</div>
{/if}

{#if !store.loaded}
	<div class="grid gap-4 {columns[density]}">
		{#each [0, 1] as i (i)}
			<div class="aspect-video animate-pulse rounded-2xl bg-surface-2"></div>
		{/each}
	</div>
{:else if store.cameras.length === 0}
	<div class="mx-auto mt-10 flex max-w-lg flex-col items-center card px-8 py-14 text-center">
		<span class="mb-5 grid size-14 place-items-center rounded-2xl bg-accent/15 text-accent"
			><Cctv class="size-7" /></span
		>
		<h2 class="text-lg font-semibold">No cameras yet</h2>
		<p class="mt-2 text-sm text-muted">
			Add your first camera to see it here. You can also edit <code class="font-mono text-text"
				>config.yaml</code
			>
			directly — Norn picks up changes on its own.
		</p>
		<a href="/cameras/new" class="mt-6 btn-primary"><Plus class="size-4" />Add camera</a>
	</div>
{:else}
	<div class="grid gap-4 {columns[density]}">
		{#each shown as camera (camera.id)}
			<CameraTile {camera} />
		{/each}
	</div>
{/if}
