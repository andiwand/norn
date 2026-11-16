<script lang="ts" module>
	export type TileView = 'auto' | 'hd' | 'sd' | 'stills';
</script>

<script lang="ts">
	// One camera on the Live page: video (or stills), its name, and what it does right now.
	import type { Camera, StreamInfo } from '../api';
	import EventBadge from './EventBadge.svelte';
	import LiveVideo from './LiveVideo.svelte';
	import RecBadge from './RecBadge.svelte';
	import RecordButton from './RecordButton.svelte';
	import StillImage from './StillImage.svelte';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import VideoOff from '@lucide/svelte/icons/video-off';

	let {
		camera,
		view = 'auto',
		arranging = false
	}: { camera: Camera; view?: TileView; arranging?: boolean } = $props();

	const main = $derived(camera.streams.find((s) => s.id === 'main') ?? camera.streams[0]);
	const small = $derived(camera.streams.find((s) => s.id === 'sub') ?? main);
	const low = $derived(camera.streams.find((s) => s.id === 'low'));
	// HD: the main stream. SD: the small one. Auto: starts small, drops to Norn's low stream
	// when the connection struggles, and comes back up after a calm.
	const stream = $derived<StreamInfo | undefined>(view === 'hd' ? main : small);
	const ladder = $derived(
		view === 'auto'
			? [small, ...(low && low.id !== small?.id ? [low] : [])].filter(Boolean)
			: undefined
	);
	let playing = $state('');
	const names: Record<string, string> = { main: 'HD', sub: 'SD', low: 'Low' };
	const offline = $derived(camera.device && !camera.device.online);
</script>

<div class="group/tile relative">
	<a
		href={arranging ? undefined : `/cameras/${camera.id}`}
		class="group relative block aspect-video overflow-hidden rounded-2xl border border-line bg-black shadow-[0_20px_50px_-30px_rgb(0_0_0/0.8)] ring-accent/0 transition {arranging
			? 'cursor-grab'
			: 'hover:ring-2 hover:ring-accent/50'}"
		draggable="false"
	>
		{#if camera.error}
			<div class="grid h-full place-items-center bg-surface-2 p-6 text-center">
				<div class="flex flex-col items-center gap-2">
					<TriangleAlert class="size-6 text-warning" />
					<p class="text-sm text-muted">{camera.error}</p>
				</div>
			</div>
		{:else if !camera.enabled || !stream}
			<div class="grid h-full place-items-center bg-surface-2 text-muted">
				<div class="flex flex-col items-center gap-2 text-sm">
					<VideoOff class="size-6" />
					{camera.enabled ? 'No stream' : 'Disabled'}
				</div>
			</div>
		{:else if view === 'stills' || arranging}
			<!-- A slow stream of stills: hardly any network or CPU, for many cameras at once. -->
			<StillImage camera={camera.id} class="h-full w-full" />
		{:else}
			{#key stream.id + (ladder ? ':auto' : '')}
				<LiveVideo
					camera={camera.id}
					stream={stream.id}
					codec={stream.codec}
					{ladder}
					bind:playing
					fit="cover"
					class="h-full w-full"
				/>
			{/key}
		{/if}

		<div
			class="pointer-events-none absolute inset-x-0 bottom-0 flex items-end justify-between gap-2 bg-gradient-to-t from-black/75 via-black/30 to-transparent px-4 pt-10 pb-3"
		>
			<span class="truncate text-sm font-semibold text-white drop-shadow">{camera.name}</span>
			{#if view !== 'stills' && !arranging && playing && names[playing]}
				<span
					class="shrink-0 rounded bg-black/50 px-1.5 py-0.5 text-[10px] font-semibold text-white/80"
					>{names[playing]}</span
				>
			{/if}
		</div>
		<div class="absolute top-3 left-3 flex gap-2">
			{#if camera.recording}<RecBadge mode={camera.recording.mode} />{/if}
			{#if camera.events}<EventBadge active={camera.events.active} />{/if}
			{#if offline}
				<span class="badge bg-danger/85 text-white" title={camera.device?.error ?? ''}>Offline</span
				>
			{/if}
		</div>
	</a>
	{#if !arranging}
		<!-- Beside the link, not in it: a button inside a link is no valid HTML. With a mouse it shows
	     on hover; touch screens can't hover. A running clip always shows its stop button. -->
		<RecordButton
			{camera}
			class="absolute top-2.5 right-2.5 {camera.recording?.mode === 'clip'
				? ''
				: 'pointer-fine:opacity-0 pointer-fine:group-hover/tile:opacity-100 pointer-fine:focus-visible:opacity-100'}"
		/>
	{/if}
</div>
