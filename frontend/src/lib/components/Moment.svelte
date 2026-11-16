<script lang="ts">
	// Every camera at one moment of the timeline: the video frame then, if a recording runs,
	// else the newest picture or thumbnail before it.
	import { untrack } from 'svelte';
	import { urls, type Camera, type Recording } from '../api';
	import Film from '@lucide/svelte/icons/film';

	interface Item {
		r: Recording;
		t: number;
		end: number;
	}

	let {
		cameras,
		items,
		at,
		onopen
	}: {
		cameras: Camera[];
		items: Item[];
		/** The moment, in ms. */
		at: number;
		onopen: (r: Recording, seconds: number) => void;
	} = $props();

	interface Tile {
		camera: Camera;
		r: Recording | null;
		seconds: number; // into the recording
		src: string | null;
		before: number; // ms between the image and the moment (0: the frame then)
	}

	const tiles = $derived(
		cameras.map((camera): Tile => {
			const own = items.filter((i) => i.r.camera === camera.id);
			const video = own.find((i) => i.r.kind === 'video' && i.t <= at && at < i.end);
			if (video) {
				const seconds = Math.floor((at - video.t) / 1000);
				return { camera, r: video.r, seconds, src: urls.frame(video.r, seconds), before: 0 };
			}
			let last: Item | null = null;
			for (const i of own) if (i.r.thumbnail && i.t <= at && (!last || i.t > last.t)) last = i;
			return last
				? { camera, r: last.r, seconds: 0, src: urls.small(last.r), before: at - last.t }
				: { camera, r: null, seconds: 0, src: null, before: 0 };
		})
	);

	// Per tile: the image shown stays until the next one has loaded, and only the newest wish
	// loads, so scrubbing doesn't queue up requests.
	let shown = $state<Record<string, string | null>>({});
	const loading = new Map<string, string>();
	const wanted = new Map<string, string | null>();

	function show(camera: string, src: string | null) {
		wanted.set(camera, src);
		if (src === null || src === shown[camera]) {
			if (src === null) shown[camera] = null;
			return;
		}
		if (loading.has(camera)) return; // the load under way picks up the newest wish after
		loading.set(camera, src);
		const image = new Image();
		const done = (ok: boolean) => {
			loading.delete(camera);
			if (ok) shown[camera] = src;
			const next = wanted.get(camera) ?? null;
			if (next !== src) show(camera, next);
		};
		image.onload = () => done(true);
		image.onerror = () => done(false);
		image.src = src;
	}

	$effect(() => {
		const wishes = tiles.map((t) => [t.camera.id, t.src] as const);
		untrack(() => wishes.forEach(([camera, src]) => show(camera, src)));
	});

	function ago(ms: number): string {
		const minutes = Math.round(ms / 60_000);
		if (minutes < 1) return 'just before';
		if (minutes < 60) return `${minutes} min before`;
		const hours = Math.round(minutes / 60);
		return hours < 48 ? `${hours} h before` : `${Math.round(hours / 24)} days before`;
	}
</script>

<div
	class="grid gap-2"
	style:grid-template-columns="repeat(auto-fill, minmax(min(100%, {cameras.length > 2
		? 11
		: 16}rem), 1fr))"
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
					>{tile.r ? (tile.before ? ago(tile.before) : 'Video') : 'Nothing before'}</span
				>
			</span>
		</button>
	{/each}
</div>
