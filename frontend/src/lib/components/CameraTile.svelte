<script lang="ts">
	import type { Camera } from '../api';
	import LiveVideo from './LiveVideo.svelte';
	import RecBadge from './RecBadge.svelte';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import VideoOff from '@lucide/svelte/icons/video-off';

	let { camera }: { camera: Camera } = $props();

	// The grid uses the small stream where there is one; it costs the browser and the network less.
	const stream = $derived(camera.streams.find((s) => s.id === 'sub') ?? camera.streams[0]);
	const offline = $derived(camera.device && !camera.device.online);
	const update = $derived(camera.firmware?.status === 'update');
</script>

<a
	href="/cameras/{camera.id}"
	class="group relative block aspect-video overflow-hidden rounded-2xl border border-line bg-black shadow-[0_20px_50px_-30px_rgb(0_0_0/0.8)] ring-accent/0 transition hover:ring-2 hover:ring-accent/50"
>
	{#if camera.error}
		<div class="grid h-full place-items-center bg-surface-2 p-6 text-center">
			<div class="flex flex-col items-center gap-2">
				<TriangleAlert class="size-6 text-warning" />
				<p class="text-sm text-muted">{camera.error}</p>
			</div>
		</div>
	{:else if !camera.enabled || camera.streams.length === 0}
		<div class="grid h-full place-items-center bg-surface-2 text-muted">
			<div class="flex flex-col items-center gap-2 text-sm">
				<VideoOff class="size-6" />
				{camera.enabled ? 'No stream' : 'Disabled'}
			</div>
		</div>
	{:else}
		<LiveVideo
			camera={camera.id}
			stream={stream.id}
			codec={stream.codec}
			fit="cover"
			class="h-full w-full"
		/>
	{/if}

	<div
		class="pointer-events-none absolute inset-x-0 bottom-0 flex items-end justify-between gap-2 bg-gradient-to-t from-black/75 via-black/30 to-transparent px-4 pt-10 pb-3"
	>
		<span class="truncate text-sm font-semibold text-white drop-shadow">{camera.name}</span>
	</div>
	<div class="absolute top-3 left-3 flex gap-2">
		{#if camera.recording}<RecBadge mode={camera.recording.mode} />{/if}
		{#if offline}
			<span class="badge bg-danger/85 text-white" title={camera.device?.error ?? ''}>Offline</span>
		{:else if update}
			<span class="badge bg-warning/90 text-black" title="New firmware is available">Update</span>
		{/if}
	</div>
</a>
