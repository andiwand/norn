<script lang="ts">
	// Start a clip of a camera, or stop it: a round button on its video. While a clip runs it
	// shows the time, in red. A continuous recording runs on regardless.
	import { api, type Camera } from '../api';
	import { formatDuration } from '../format';
	import { store } from '../state.svelte';
	import CircleDot from '@lucide/svelte/icons/circle-dot';
	import Square from '@lucide/svelte/icons/square';

	let { camera, class: className = '' }: { camera: Camera; class?: string } = $props();

	const clip = $derived(camera.recording?.mode === 'clip' ? camera.recording : null);
	const available = $derived(!!store.info?.recording_available && camera.enabled);
	let now = $state(Date.now());
	$effect(() => {
		if (!clip) return;
		now = Date.now();
		const timer = setInterval(() => (now = Date.now()), 500);
		return () => clearInterval(timer);
	});
	const elapsed = $derived(
		clip?.start ? Math.max(0, (now - new Date(clip.start).getTime()) / 1000) : 0
	);

	function toggle(e: MouseEvent) {
		e.preventDefault();
		e.stopPropagation();
		if (clip) store.attempt(() => api.stopRecord(camera.id));
		else store.attempt(() => api.record(camera.id), `Recording ${camera.name}`);
	}
</script>

{#if available}
	<button
		class="inline-flex h-10 items-center justify-center gap-1.5 rounded-full backdrop-blur-md transition {clip
			? 'bg-danger px-3.5 text-sm font-semibold text-white tabular-nums hover:bg-danger/85'
			: 'w-10 bg-black/45 text-white hover:bg-danger'} {className}"
		onclick={toggle}
		aria-label={clip ? `Stop recording ${camera.name}` : `Record a clip of ${camera.name}`}
		title={clip ? 'Stop the clip' : 'Record a clip, until its length is up or you stop it'}
	>
		{#if clip}
			<Square class="size-3.5 fill-current" />{formatDuration(elapsed)}
		{:else}
			<CircleDot class="size-5" />
		{/if}
	</button>
{/if}
