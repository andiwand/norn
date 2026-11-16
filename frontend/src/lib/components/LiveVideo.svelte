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

	// With a ladder, a guard picks the stream; without, it is `stream`. The guard lives as long
	// as the ladder holds the same streams: a refresh of the camera list mustn't reset it.
	const ladderKey = $derived(ladder?.map((s) => s.id).join(',') ?? '');
	let guard = $state<QualityGuard | null>(null);
	let current = $state(untrack(() => stream));
	$effect(() => {
		const ids = ladderKey ? ladderKey.split(',') : [];
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
	let played = $state(false); // this stream showed a frame: the poster has done its job
	let poster = $state<string | null>(null);
	let error = $state('');

	// A new camera or stream: connecting again, with a fresh poster until it plays.
	$effect(() => {
		void current;
		poster = urls.still(camera);
		untrack(() => {
			status = 'connecting';
			played = false;
		});
	});

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

	// The guard watches the video all along (a stall shows as "connecting" for a moment, and
	// must count too) and steps the quality down or up.
	$effect(() => {
		const video = (element as (HTMLElement & { video?: HTMLVideoElement }) | null)?.video;
		if (!guard || !video) return;
		const g = guard;
		return watchVideo(video, (health) => {
			const next = g.check(health);
			if (next !== current) current = next;
		});
	});

	// A stream that never starts (after a step up, say) counts as failed. One that played and
	// reconnects for a moment doesn't.
	$effect(() => {
		if (!guard || status !== 'connecting' || played) return;
		const g = guard;
		const timer = setTimeout(() => {
			const next = g.down();
			if (next !== current) current = next;
		}, 15_000);
		return () => clearTimeout(timer);
	});

	function onState(e: Event) {
		status = (e as CustomEvent).detail;
		if (status === 'playing') {
			error = '';
			played = true;
		}
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
	<!-- A new element per stream: go2rtc's player only connects once (a new src waits for the
	     next reconnect otherwise). -->
	{#key current}
		<norn-video
			bind:this={element}
			{fit}
			class="block h-full w-full"
			onnorn-state={onState}
			onnorn-mode={onMode}
			onnorn-error={onError}
		></norn-video>
	{/key}

	{#if !played && poster}
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
