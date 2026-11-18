<script lang="ts">
	// A camera's recent clips, over 24 hours, 3 or 7 days: on a strip (a tap opens one), the
	// newest of them as tiles, and when there are none, why: nothing set to record, or recording
	// not possible.
	import { api, type Camera, type Recording } from '../api';
	import { formatTime, triggerLabel } from '../format';
	import { RecordingList } from '../recordings.svelte';
	import { store } from '../state.svelte';
	import { readStoredJson, writeStored } from '../stored';
	import RecordingTile from './RecordingTile.svelte';

	let {
		camera,
		onopen,
		onsettings
	}: {
		camera: Camera;
		onopen: (r: Recording) => void;
		/** Show this camera's recording settings. */
		onsettings: () => void;
	} = $props();

	const DAY = 24 * 3600 * 1000;
	const RANGES = [
		[1, '24 h', 'the last 24 hours'],
		[3, '3 days', 'the last 3 days'],
		[7, '7 days', 'the last 7 days']
	] as const;
	type Days = (typeof RANGES)[number][0];
	const RANGE_KEY = 'norn.activity-days';
	let days = $state<Days>(RANGES.find(([d]) => d === readStoredJson(RANGE_KEY, 1))?.[0] ?? 1);
	const range = $derived(days * DAY);
	const rangeText = $derived(RANGES.find(([d]) => d === days)?.[2] ?? '');

	const list = new RecordingList();
	let loaded = $state(false);
	let now = $state(Date.now());

	let asked = 0; // only the answer to the newest request counts
	async function load(id: string, rangeMs: number) {
		const mine = ++asked;
		const start = Date.now();
		const since = new Date(start - rangeMs).toISOString();
		// Clips only: a week of continuous files would be a thousand.
		const got = await api
			.recordings({ camera: id, since, kind: 'video', trigger: 'clips', limit: 2000 })
			.catch(() => null);
		if (mine !== asked) return;
		now = start;
		list.items = got?.recordings ?? [];
		loaded = true;
	}

	function pick(next: Days) {
		days = next;
		writeStored(RANGE_KEY, JSON.stringify(next));
	}

	// The id only: the camera object is replaced on each refresh.
	const id = $derived(camera.id);
	$effect(() => {
		const cameraId = id;
		const rangeMs = range;
		load(cameraId, rangeMs);
		const timer = setInterval(() => (now = Date.now()), 60_000);
		const off = store.on((event) => {
			if (event.data.camera !== cameraId) return;
			if (event.type === 'recording.finished' || event.type === 'recording.deleted')
				load(cameraId, rangeMs);
		});
		return () => {
			clearInterval(timer);
			off();
		};
	});

	/** The page's dialog pinned or changed a recording: show it so here too. */
	export function replace(r: Recording) {
		list.replace(r);
	}

	const clips = $derived(list.items);
	const continuous = $derived(camera.record === 'continuous');

	const at = (r: Recording) => (new Date(r.start).getTime() - (now - range)) / range;
	// Over days, a time alone doesn't say which day.
	const when = (r: Recording) =>
		days === 1
			? formatTime(r.start)
			: new Date(r.start).toLocaleString([], {
					weekday: 'short',
					hour: '2-digit',
					minute: '2-digit'
				});
	const span = (r: Recording) => ((r.duration ?? 30) * 1000) / range;
	const colour = (trigger: string) =>
		trigger === 'manual' || trigger === 'webhook'
			? 'bg-accent'
			: trigger === 'motion'
				? 'bg-accent-2'
				: 'bg-warning';

	const counts = $derived(
		Object.entries(
			clips.reduce<Record<string, number>>(
				(n, r) => ({ ...n, [r.trigger]: (n[r.trigger] ?? 0) + 1 }),
				{}
			)
		).sort((a, b) => b[1] - a[1])
	);

	// Along the strip: over a day every 6 hours; over days each midnight, named by its day
	// (and over 3 days noon too, as a line without a label).
	const ticks = $derived.by(() => {
		const out: { x: number; label: string }[] = [];
		const from = now - range;
		const first = new Date(from);
		first.setMinutes(0, 0, 0);
		for (let t = first.getTime() + 3600_000; t < now; t += 3600_000) {
			const d = new Date(t);
			const h = d.getHours();
			const x = (t - from) / range;
			if (days === 1 && h % 6 === 0) out.push({ x, label: `${String(h).padStart(2, '0')}:00` });
			else if (days > 1 && h === 0)
				out.push({ x, label: d.toLocaleDateString([], { weekday: 'short', day: 'numeric' }) });
			else if (days === 3 && h === 12) out.push({ x, label: '' });
		}
		return out;
	});

	// Why there are no clips, from what applies to this camera (its own, its circle's, the global).
	const effectiveTriggers = $derived.by(() => {
		if (camera.triggers != null) return camera.triggers;
		const circle = store.circles.find((c) => c.cameras.includes(camera.id));
		return circle?.triggers ?? store.info?.recording.triggers ?? [];
	});
	const reason = $derived(
		!store.info?.recording_available
			? 'Recording is not possible: Norn needs go2rtc and FFmpeg.'
			: !camera.enabled
				? 'This camera is disabled.'
				: !effectiveTriggers.length
					? 'Nothing is set to start clips of this camera.'
					: `No ${effectiveTriggers.map(triggerLabel).join(', ').toLowerCase()} in ${rangeText}.`
	);
</script>

<section class="card p-4">
	<div class="mb-3 flex flex-wrap items-center gap-x-3 gap-y-2">
		<h2 class="text-sm font-semibold">Activity</h2>
		<div class="flex rounded-lg bg-surface-3 p-0.5" role="radiogroup" aria-label="Show">
			{#each RANGES as [d, label] (d)}
				<button
					role="radio"
					aria-checked={days === d}
					class="rounded-md px-2.5 py-1 text-xs font-medium whitespace-nowrap transition {days === d
						? 'bg-surface text-text shadow'
						: 'text-muted hover:text-text'}"
					onclick={() => pick(d)}>{label}</button
				>
			{/each}
		</div>
		<span class="min-w-0 flex-1 truncate text-xs text-muted">
			{#if !loaded}…{:else if clips.length}
				{clips.length}
				{clips.length === 1 ? 'clip' : 'clips'}{#if continuous}
					· recording continuously{/if}
			{:else if continuous}Recording continuously{/if}
		</span>
		<a href="/recordings?camera={camera.id}" class="shrink-0 text-sm text-accent hover:underline"
			>All recordings</a
		>
	</div>

	<!-- The strip: a mark per clip, as wide as it ran (at least a few pixels). -->
	<div class="relative h-9 rounded-lg bg-surface-2">
		{#each ticks as t (t.x)}
			<span class="absolute inset-y-0 w-px bg-line" style="left:{t.x * 100}%"></span>
		{/each}
		{#each clips as r (r.id)}
			<button
				class="absolute inset-y-1.5 min-w-1 rounded-sm opacity-90 transition hover:inset-y-0.5 hover:opacity-100 focus-visible:inset-y-0.5 {colour(
					r.trigger
				)}"
				style="left:{Math.max(0, at(r)) * 100}%;width:{span(r) * 100}%"
				title="{triggerLabel(r.trigger)} · {when(r)}"
				aria-label="{triggerLabel(r.trigger)} at {when(r)}: play"
				onclick={() => onopen(r)}
			></button>
		{/each}
		<span class="absolute inset-y-0 right-0 w-0.5 rounded bg-accent" title="Now"></span>
	</div>
	<div class="relative mt-1 h-4 text-[11px] text-muted tabular-nums">
		{#each ticks as t (t.x)}
			<span class="absolute -translate-x-1/2" style="left:{t.x * 100}%">{t.label}</span>
		{/each}
	</div>

	{#if counts.length}
		<div class="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
			{#each counts as [trigger, n] (trigger)}
				<span class="flex items-center gap-1.5"
					><span class="h-2.5 w-1 rounded-sm {colour(trigger)}"></span>{triggerLabel(trigger)}
					{n}</span
				>
			{/each}
		</div>
	{/if}

	{#if clips.length}
		<div class="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
			{#each clips.slice(0, 4) as r (r.id)}
				<RecordingTile
					recording={r}
					cameraName={camera.name}
					{onopen}
					ondelete={list.remove}
					onpin={list.pin}
				/>
			{/each}
		</div>
	{:else if loaded}
		<p class="mt-3 text-sm text-muted">
			{reason}
			{#if store.info?.recording_available && camera.enabled}
				<button class="text-accent hover:underline" onclick={onsettings}>Recording settings</button>
			{/if}
		</p>
	{/if}
</section>
