<script lang="ts">
	// Live video of one stream, through go2rtc: WebRTC first, MSE/HLS as fallback.
	import '../go2rtc/norn-video.js';
	import { urls } from '../api';
	import LoaderCircle from '@lucide/svelte/icons/loader-circle';
	import VideoOff from '@lucide/svelte/icons/video-off';

	interface Props {
		camera: string;
		stream?: string;
		fit?: 'contain' | 'cover';
		muted?: boolean;
		mode?: string | null;
		element?: HTMLElement | null;
		class?: string;
	}

	let {
		camera,
		stream = 'main',
		fit = 'contain',
		muted = true,
		mode = $bindable(null),
		element = $bindable(null),
		class: className = ''
	}: Props = $props();

	let status = $state<'connecting' | 'playing' | 'error'>('connecting');
	let error = $state('');

	$effect(() => {
		const el = element as (HTMLElement & { src: string }) | null;
		if (!el) return;
		el.src = urls.stream(camera, stream);
	});

	$effect(() => {
		const video = (element as (HTMLElement & { video?: HTMLVideoElement }) | null)?.video;
		if (video) video.muted = muted;
	});

	function onState(e: Event) {
		status = (e as CustomEvent).detail;
		if (status === 'playing') error = '';
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
