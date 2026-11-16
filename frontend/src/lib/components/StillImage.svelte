<script lang="ts">
	// A camera as stills, one every `every` seconds: a short request each time, so many tiles
	// don't hold the browser's few connections open; nothing while hidden or off screen.
	import { urls } from '../api';

	let {
		camera,
		every = 2,
		class: className = ''
	}: { camera: string; every?: number; class?: string } = $props();

	let shown = $state<string | null>(null);
	let box = $state<HTMLElement>();
	let visible = $state(true);
	let pageVisible = $state(typeof document === 'undefined' || !document.hidden);

	$effect(() => {
		const onVisibility = () => (pageVisible = !document.hidden);
		document.addEventListener('visibilitychange', onVisibility);
		return () => document.removeEventListener('visibilitychange', onVisibility);
	});

	$effect(() => {
		if (!box) return;
		const observer = new IntersectionObserver(([entry]) => (visible = entry.isIntersecting));
		observer.observe(box);
		return () => observer.disconnect();
	});

	// Load the next still in the background and show it once it's there: no flicker.
	$effect(() => {
		if (!visible || !pageVisible) return;
		let stopped = false;
		let timer: ReturnType<typeof setTimeout> | undefined;
		const next = () => {
			const image = new Image();
			// The camera sends keyframes every few seconds: a still that old is still the newest.
			const url = urls.still(camera, Math.max(10, every * 3));
			const again = () => {
				if (!stopped) timer = setTimeout(next, every * 1000);
			};
			image.onload = () => {
				if (!stopped) shown = url;
				again();
			};
			image.onerror = again;
			image.src = url;
		};
		next();
		return () => {
			stopped = true;
			clearTimeout(timer);
		};
	});
</script>

<div bind:this={box} class="relative bg-black {className}">
	{#if shown}<img src={shown} alt="" class="h-full w-full object-cover" />{/if}
</div>
