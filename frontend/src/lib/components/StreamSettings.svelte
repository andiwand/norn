<script lang="ts">
	// The camera's streams, as testing found them: switch each on or off. A camera that serves
	// one stream at a time gets a single choice.
	import { api, type Camera } from '../api';
	import { store } from '../state.svelte';
	import RefreshCw from '@lucide/svelte/icons/refresh-cw';

	let { camera, value = $bindable() }: { camera: Camera; value: string[] | null } = $props();

	let testing = $state(false);
	const single = $derived(camera.concurrent === false);
	const usable = $derived(camera.stream_options.filter((o) => !o.probe || o.probe.ok));
	const on = $derived(value ?? camera.stream_options.filter((o) => o.active).map((o) => o.id));

	function describe(o: (typeof camera.stream_options)[number]): string {
		const p = o.probe;
		if (!p) return 'Not tested';
		if (!p.ok) return `Doesn't work: ${p.error}`;
		return [
			p.width && p.height ? `${p.width}×${p.height}` : null,
			p.codec?.toUpperCase(),
			p.fps ? `${p.fps} fps` : null
		]
			.filter(Boolean)
			.join(' · ');
	}

	function toggle(id: string) {
		if (single) {
			value = [id];
			return;
		}
		const next = on.includes(id) ? on.filter((x) => x !== id) : [...on, id];
		if (next.length) value = next; // at least one stays on
	}

	async function test() {
		testing = true;
		await store.attempt(() => api.probeStreams(camera.id), 'Streams tested');
		await store.refresh();
		testing = false;
	}
</script>

<div class="px-5 py-3.5">
	<div class="flex flex-wrap items-center justify-between gap-x-6 gap-y-2">
		<div class="min-w-0 flex-1 basis-56">
			<span class="block text-sm font-medium">Streams</span>
			<span class="mt-0.5 block text-xs text-muted">
				{#if single}
					This camera serves one stream at a time: pick it.
				{:else}
					Norn uses the streams that are on: the best for viewing and recording, the smallest for
					weak connections and stills.
				{/if}
			</span>
		</div>
		<button type="button" class="chip" onclick={test} disabled={testing}>
			<RefreshCw class="size-3.5 {testing ? 'animate-spin' : ''}" />{testing
				? 'Testing…'
				: 'Test again'}
		</button>
	</div>
	<div class="mt-2 space-y-1.5">
		{#each camera.stream_options as o (o.id)}
			{@const works = !o.probe || o.probe.ok}
			<label
				class="flex items-center gap-3 rounded-xl bg-surface-2/60 px-3 py-2 {works
					? 'cursor-pointer'
					: 'opacity-60'}"
			>
				<input
					type={single ? 'radio' : 'checkbox'}
					name="stream-{camera.id}"
					class={single ? 'size-4 accent-[var(--accent)]' : 'switch'}
					checked={on.includes(o.id)}
					disabled={!works || (on.length === 1 && on.includes(o.id) && !single)}
					onchange={() => toggle(o.id)}
				/>
				<span class="min-w-0 flex-1">
					<span class="block text-sm font-medium">{o.label}</span>
					<span class="block truncate text-xs text-muted">{describe(o)}</span>
				</span>
			</label>
		{/each}
		{#if !usable.length}
			<p class="text-xs text-muted">No stream works right now.</p>
		{/if}
	</div>
</div>
