<script lang="ts">
	// Live video of one stream, through go2rtc: WebRTC first, MSE/HLS as fallback.
	import '../go2rtc/norn-video.js';
	import { urls, type StreamInfo } from '../api';
	import { QualityGuard, watchVideo } from '../quality';
	import { untrack } from 'svelte';
	import LoaderCircle from '@lucide/svelte/icons/loader-circle';
	import VideoOff from '@lucide/svelte/icons/video-off';

	interface Props {
		camera: string;
		stream?: string;
		codec?: string | null;
		fit?: 'contain' | 'cover';
		muted?: boolean;
		mode?: string | null;
		element?: HTMLElement | null;
		class?: string;
		/** Adapt the quality: the streams from best to worst; `stream` is where it starts. */
		ladder?: StreamInfo[];
		/** The stream playing now (with `ladder`, it changes on its own). */
		playing?: string;
	}

	let {
		camera,
		stream = 'main',
		codec = null,
		fit = 'contain',
		muted = true,
		mode = $bindable(null),
		element = $bindable(null),
		class: className = '',
		ladder,
		playing = $bindable(stream)
	}: Props = $props();

	// With a ladder, a guard picks the stream; without, it is `stream`.
	let guard = $state<QualityGuard | null>(null);
	let current = $state(untrack(() => stream));
	$effect(() => {
		const ids = ladder?.map((s) => s.id) ?? [];
		const start = Math.max(0, ids.indexOf(stream));
		untrack(() => {
			guard = ids.length > 1 ? new QualityGuard(ids, start) : null;
			current = guard?.stream ?? stream;
		});
	});
	$effect(() => {
		playing = current;
	});
	const currentCodec = $derived(ladder?.find((s) => s.id === current)?.codec ?? codec);

	let status = $state<'connecting' | 'playing' | 'error'>('connecting');
	let poster = $state<string | null>(null);
	$effect(() => {
		poster = urls.still(camera);
	});
	let error = $state('');

	$effect(() => {
		const el = element as (HTMLElement & { src: string; mode: string }) | null;
		if (!el) return;
		// MJPEG can't go over WebRTC or MSE; go2rtc sends it as JPEG frames instead.
		el.mode = currentCodec === 'mjpeg' ? 'mjpeg' : 'webrtc,mse,hls,mjpeg';
		el.src = urls.stream(camera, current);
	});

	$effect(() => {
		const video = (element as (HTMLElement & { video?: HTMLVideoElement }) | null)?.video;
		if (video) video.muted = muted;
	});

	// While it plays, the guard watches the video and steps the quality down or up.
	$effect(() => {
		const video = (element as (HTMLElement & { video?: HTMLVideoElement }) | null)?.video;
		if (!guard || !video || status !== 'playing') return;
		const g = guard;
		return watchVideo(video, (health) => {
			const next = g.check(health);
			if (next !== current) current = next;
		});
	});

	function onState(e: Event) {
		status = (e as CustomEvent).detail;
		if (status === 'playing') error = '';
		if (status === 'error' && guard) {
			const next = guard.down(); // it doesn't play at all: try a lighter stream
			if (next !== current) current = next;
		}
	}
	function onMode(e: Event) {
		mode = (e as CustomEvent).detail;
		const video = (element as HTMLElement & { video?: HTMLVideoElement })?.video;
		if (video) video.muted = muted;
	}
	function onError(e: Event) {
		error = String((e as CustomEvent).detail ?? 'Stream error');
	}
</script>

<div class="relative overflow-hidden bg-black {className}">
	<norn-video
		bind:this={element}
		{fit}
		class="block h-full w-full"
		onnorn-state={onState}
		onnorn-mode={onMode}
		onnorn-error={onError}
	></norn-video>

	{#if status !== 'playing' && poster}
		<!-- The newest still until the video plays: the wait for a keyframe isn't a black box. -->
		<img
			src={poster}
			alt=""
			class="pointer-events-none absolute inset-0 h-full w-full {fit === 'cover'
				? 'object-cover'
				: 'object-contain'}"
			onerror={() => (poster = null)}
		/>
	{/if}
	{#if status !== 'playing'}
		<div
			class="pointer-events-none absolute inset-0 grid place-items-center bg-gradient-to-b from-black/30 to-black/60 text-white/80"
		>
			{#if status === 'error'}
				<div class="flex max-w-[80%] flex-col items-center gap-2 text-center">
					<VideoOff class="size-7 opacity-80" />
					<span class="line-clamp-2 text-xs">{error || 'No video'}</span>
				</div>
			{:else}
				<LoaderCircle class="size-7 animate-spin opacity-70" />
			{/if}
		</div>
	{/if}
</div>
