<script lang="ts">
	// What Norn's AI sees on the camera's newest still, drawn over the video: a box per object,
	// solid when it starts clips, dashed when Norn ignores it (seen too briefly yet, or not
	// moving: a parked car, a sheet on a chair). The stills come every few seconds, so the boxes
	// can trail the video a little.
	import type { SeenObject } from '../api';
	import { store } from '../state.svelte';
	import ObjectBoxes from './ObjectBoxes.svelte';

	let { camera }: { camera: string } = $props();

	let objects = $state<SeenObject[]>([]);
	let at = 0;

	$effect(() => {
		const id = camera;
		objects = [];
		const off = store.on((event) => {
			if (event.type !== 'camera.objects' || event.data.camera !== id) return;
			objects = (event.data.objects as SeenObject[]) ?? [];
			at = Date.now();
		});
		// No news for a while (detection switched off, the connection dropped): nothing stale.
		const timer = setInterval(() => {
			if (objects.length && Date.now() - at > 15_000) objects = [];
		}, 5_000);
		return () => {
			off();
			clearInterval(timer);
		};
	});
</script>

<ObjectBoxes {objects} />
