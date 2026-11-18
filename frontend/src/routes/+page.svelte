<script lang="ts">
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { store } from '#lib/state.svelte.js';
	import Settings2 from '@lucide/svelte/icons/settings-2';
	import CameraTile, { type TileView } from '#lib/components/CameraTile.svelte';
	import { api } from '#lib/api.js';
	import { readStored, writeStored } from '#lib/stored.js';
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';
	import ArrowRight from '@lucide/svelte/icons/arrow-right';
	import GripVertical from '@lucide/svelte/icons/grip-vertical';
	import ArrowDownUp from '@lucide/svelte/icons/arrow-down-up';
	import Plus from '@lucide/svelte/icons/plus';
	import Cctv from '@lucide/svelte/icons/cctv';
	import Columns2 from '@lucide/svelte/icons/columns-2';
	import LayoutGrid from '@lucide/svelte/icons/layout-grid';
	import Grid3x3 from '@lucide/svelte/icons/grid-3x3';

	type Density = 1 | 2 | 3;
	let density = $state<Density>(loadDensity());

	function loadDensity(): Density {
		const value = Number(readStored('norn.density'));
		return value === 1 || value === 2 || value === 3 ? value : 2;
	}
	function setDensity(value: Density) {
		density = value;
		writeStored('norn.density', String(value));
	}

	// How the tiles show: Auto adapts to the connection; HD and SD are fixed; Stills is a
	// picture every few seconds. Remembered in this browser.
	const VIEWS: [TileView, string, string][] = [
		['auto', 'Auto', 'SD, lower when the connection struggles'],
		['hd', 'HD', 'Every camera in full quality'],
		['sd', 'SD', 'The small stream: light on mobile data'],
		['stills', 'Stills', 'A picture every 2 seconds: almost no data']
	];
	let view = $state<TileView>(loadView());
	function loadView(): TileView {
		const saved =
			readStored('norn.view') ?? (readStored('norn.stills') === '1' ? 'stills' : 'auto');
		return (['auto', 'hd', 'sd', 'stills'] as const).find((v) => v === saved) ?? 'auto';
	}
	function setView(value: TileView) {
		view = value;
		writeStored('norn.view', value);
	}

	// Arranging: drag tiles (or move them with the arrows), then save the order in config.yaml.
	let arranging = $state(false);
	let order = $state<string[]>([]);
	let dragged = $state<string | null>(null);
	let savingOrder = $state(false);
	function arrange() {
		order = store.cameras.map((c) => c.id);
		arranging = true;
	}
	function moveTo(id: string, index: number) {
		const rest = order.filter((x) => x !== id);
		rest.splice(Math.max(0, Math.min(rest.length, index)), 0, id);
		order = rest;
	}
	async function done() {
		// A camera removed meanwhile (another tab, config.yaml) drops out.
		order = order.filter((id) => store.camera(id));
		const before = store.cameras.map((c) => c.id).join(',');
		if (order.join(',') !== before) {
			savingOrder = true;
			const ok = await store.attempt(() => api.orderCameras(order), 'Order saved');
			savingOrder = false;
			if (!ok) return;
			await store.refresh();
		}
		arranging = false;
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
		arranging
			? order.map((id) => store.camera(id)).filter((c) => c !== undefined)
			: circle
				? store.cameras.filter((c) => circle.cameras.includes(c.id))
				: store.cameras
	);

	function showCircle(id: string) {
		goto(id ? `/?circle=${encodeURIComponent(id)}` : '/', { replaceState: true });
	}
</script>

<svelte:head><title>Live · Norn</title></svelte:head>

<div class="mb-6 flex flex-wrap items-end justify-between gap-4">
	<div>
		<h1 class="page-title">Live</h1>
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
		<div
			class="flex rounded-xl border border-line bg-surface-2/70 p-1"
			role="radiogroup"
			aria-label="Quality"
		>
			{#each VIEWS as [value, label, hint] (value)}
				<button
					class="h-8 rounded-lg px-2.5 text-xs font-medium transition {view === value
						? 'bg-surface-3 text-text'
						: 'text-muted hover:text-text'}"
					role="radio"
					aria-checked={view === value}
					title={hint}
					onclick={() => setView(value)}>{label}</button
				>
			{/each}
		</div>
		{#if arranging}
			<button class="btn-ghost" onclick={() => (arranging = false)} disabled={savingOrder}
				>Cancel</button
			>
			<button class="btn-primary" onclick={done} disabled={savingOrder}
				>{savingOrder ? 'Saving…' : 'Done'}</button
			>
		{:else if store.cameras.length > 1}
			<button class="btn-ghost" onclick={arrange} title="Change the order of the cameras"
				><ArrowDownUp class="size-4" /><span class="hidden sm:inline">Arrange</span></button
			>
		{/if}
		{#if !arranging}
			<a href="/cameras/new" class="btn-primary"
				><Plus class="size-4" /><span class="hidden sm:inline">Add camera</span></a
			>
		{/if}
	</div>
</div>

{#if arranging}
	<p class="mb-4 rounded-xl bg-accent/10 px-4 py-2.5 text-sm text-accent">
		Drag the cameras into the order you want, or move them with the arrows. The order is saved for
		everyone.
	</p>
{/if}

{#if store.cameras.length && !arranging}
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
		{#each shown as camera, i (camera.id)}
			{#if arranging}
				<!-- svelte-ignore a11y_no_static_element_interactions -->
				<div
					class="relative rounded-2xl transition {dragged === camera.id ? 'opacity-40' : ''}"
					draggable="true"
					ondragstart={(e) => {
						dragged = camera.id;
						e.dataTransfer?.setData('text/plain', camera.id);
					}}
					ondragover={(e) => {
						e.preventDefault();
						if (dragged && dragged !== camera.id) moveTo(dragged, order.indexOf(camera.id));
					}}
					ondragend={() => (dragged = null)}
				>
					<CameraTile {camera} arranging />
					<div
						class="absolute inset-x-0 top-1/2 flex -translate-y-1/2 items-center justify-between px-3"
					>
						<button
							class="glass-btn"
							aria-label="Earlier"
							disabled={i === 0}
							onclick={() => moveTo(camera.id, i - 1)}><ArrowLeft class="size-4" /></button
						>
						<span class="pointer-events-none glass-btn"><GripVertical class="size-4" /></span>
						<button
							class="glass-btn"
							aria-label="Later"
							disabled={i === shown.length - 1}
							onclick={() => moveTo(camera.id, i + 1)}><ArrowRight class="size-4" /></button
						>
					</div>
				</div>
			{:else}
				<CameraTile {camera} {view} />
			{/if}
		{/each}
	</div>
{/if}
