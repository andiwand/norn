<script lang="ts" module>
	import type { Recording } from '../api';

	/** A recording on the timeline, its start and end in ms. */
	export interface TimelineItem {
		r: Recording;
		t: number;
		end: number;
	}
</script>

<script lang="ts">
	// Every camera at one moment of the timeline: the video frame then, if a recording runs,
	// else the newest picture or thumbnail before it.
	import { untrack } from 'svelte';
	import { urls, type Camera } from '../api';
	import Film from '@lucide/svelte/icons/film';

	let {
		cameras,
		items,
		at,
		onopen
	}: {
		cameras: Camera[];
		items: TimelineItem[];
		at: number; // ms
		onopen: (r: Recording, seconds: number) => void;
	} = $props();

	const byCamera = $derived(Map.groupBy(items, (i) => i.r.camera));

	const tiles = $derived(
		cameras.map((camera) => {
			const own = byCamera.get(camera.id) ?? [];
			const video = own.find((i) => i.r.kind === 'video' && i.t <= at && at < i.end);
			if (video) {
				const seconds = Math.floor((at - video.t) / 1000);
				return { camera, r: video.r, seconds, src: urls.frame(video.r, seconds), before: 0 };
			}
			let last: TimelineItem | null = null;
			for (const i of own)
				if (i.r.thumbnail && i.end <= at && (!last || i.end > last.end)) last = i;
			if (!last) return { camera, r: null, seconds: 0, src: null, before: 0 };
			return { camera, r: last.r, seconds: 0, src: urls.small(last.r), before: at - last.end };
		})
	);

	// Each tile keeps its image until the next has loaded, and only the newest wish loads, so
	// scrubbing doesn't queue requests. A frame that fails falls back to the thumbnail.
	let shown = $state<Record<string, string | null>>({});
	const loading = new Set<string>();
	const wanted = new Map<string, string | null>();

	function show(camera: string, src: string | null, fallback: string | null = null) {
		wanted.set(camera, src);
		if (src === null) return void (shown[camera] = null);
		if (src === shown[camera] || loading.has(camera)) return;
		loading.add(camera);
		const image = new Image();
		const done = (ok: boolean) => {
			loading.delete(camera);
			shown[camera] = ok ? src : fallback;
			const next = wanted.get(camera) ?? null;
			if (next !== src) show(camera, next);
		};
		image.onload = () => done(true);
		image.onerror = () => done(false);
		image.src = src;
	}

	$effect(() => {
		for (const t of tiles) {
			const fallback = t.r && t.before === 0 ? urls.small(t.r) : null;
			untrack(() => show(t.camera.id, t.src, fallback));
		}
	});

	function ago(ms: number): string {
		const minutes = Math.round(ms / 60_000);
		if (minutes < 1) return 'just before';
		if (minutes < 60) return `${minutes} min before`;
		const hours = Math.round(minutes / 60);
		return hours < 48 ? `${hours} h before` : `${Math.round(hours / 24)} days before`;
	}
</script>

<!-- On a phone two to a row, so the tracks below stay in view. -->
<div
	class="grid gap-2"
	style:grid-template-columns="repeat(auto-fill, minmax({cameras.length > 1
		? `min(${cameras.length > 2 ? 11 : 16}rem, calc(50% - 0.25rem))`
		: 'min(100%, 16rem)'}, 1fr))"
>
	{#each tiles as tile (tile.camera.id)}
		{@const src = shown[tile.camera.id]}
		<button
			class="group relative aspect-video overflow-hidden rounded-xl bg-surface-2 text-left disabled:cursor-default"
			disabled={!tile.r}
			onclick={() => tile.r && onopen(tile.r, tile.seconds)}
		>
			{#if src && tile.src}
				<img {src} alt="" class="h-full w-full object-cover {tile.before ? 'opacity-70' : ''}" />
			{:else}
				<span class="grid h-full place-items-center text-muted/40"><Film class="size-5" /></span>
			{/if}
			<span
				class="absolute inset-x-0 bottom-0 flex items-end justify-between gap-2 bg-gradient-to-t from-black/70 to-transparent px-2.5 pt-6 pb-1.5 text-white"
			>
				<span class="truncate text-xs font-semibold">{tile.camera.name}</span>
				<span class="shrink-0 text-[10px] font-medium text-white/80"
					>{tile.r ? (tile.before ? ago(tile.before) : 'Video') : 'Nothing in range'}</span
				>
			</span>
		</button>
	{/each}
</div>
