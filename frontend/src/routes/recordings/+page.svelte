<script lang="ts">
	// Recordings in four views: Events (clips grouped into what happened, the default), the
	// Timeline, Continuous files and the Pictures on a timer. One filter row for all of them; the
	// view, the camera and the trigger are in the URL.
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { tick } from 'svelte';
	import { api, type Recording } from '#lib/api.js';
	import { store } from '#lib/state.svelte.js';
	import { RecordingList } from '#lib/recordings.svelte.js';
	import { formatDay, localDay, triggerLabel } from '#lib/format.js';
	import { groupEvents, heatMap, type ClipEvent } from '#lib/events.js';
	import { readRecentDays, writeRecentDays, type RecentDays } from '#lib/periods.js';
	import RecordingTile from '#lib/components/RecordingTile.svelte';
	import RecordingDialog from '#lib/components/RecordingDialog.svelte';
	import Timeline from '#lib/components/Timeline.svelte';
	import EventCard from '#lib/components/EventCard.svelte';
	import HeatMap from '#lib/components/HeatMap.svelte';
	import TriggerIcon from '#lib/components/TriggerIcon.svelte';
	import Zap from '@lucide/svelte/icons/zap';
	import ChartGantt from '@lucide/svelte/icons/chart-gantt';
	import Video from '@lucide/svelte/icons/video';
	import Image from '@lucide/svelte/icons/image';
	import RefreshCw from '@lucide/svelte/icons/refresh-cw';

	const TABS = [
		{ id: 'events', label: 'Events', icon: Zap },
		{ id: 'timeline', label: 'Timeline', icon: ChartGantt },
		{ id: 'continuous', label: 'Continuous', icon: Video },
		{ id: 'pictures', label: 'Pictures', icon: Image }
	] as const;
	type Tab = (typeof TABS)[number]['id'];

	const params = $derived(page.url.searchParams);
	const camera = $derived(params.get('camera') ?? '');
	// Older links: ?view=grid&trigger=pictures|continuous|clips, ?view=timeline.
	const tab = $derived.by<Tab>(() => {
		const t = params.get('tab');
		if (TABS.some((x) => x.id === t)) return t as Tab;
		if (params.get('view') === 'timeline') return 'timeline';
		const old = params.get('trigger');
		if (old === 'pictures' || old === 'continuous') return old;
		return 'events';
	});
	const trigger = $derived.by(() => {
		const t = params.get('trigger') ?? '';
		return ['clips', 'pictures', 'continuous'].includes(t) ? '' : t;
	});

	const names = $derived(Object.fromEntries(store.cameras.map((c) => [c.id, c.name])));
	const nameOf = (id: string) => names[id] ?? id;
	const shownCameras = $derived(
		camera ? store.cameras.filter((c) => c.id === camera) : store.cameras
	);

	function navigate(changes: Record<string, string>) {
		const url = new URL(page.url.href);
		url.searchParams.delete('view'); // replaced by tab
		for (const [key, value] of Object.entries(changes)) {
			if (value) url.searchParams.set(key, value);
			else url.searchParams.delete(key);
		}
		if (url.searchParams.get('tab') === 'events') url.searchParams.delete('tab');
		const old = url.searchParams.get('trigger');
		if (old && ['clips', 'pictures', 'continuous'].includes(old))
			url.searchParams.delete('trigger');
		goto(url, { replace: true, reset: false });
	}

	// --- Loading: each list view loads its own kind of recordings, filtered by the server.
	const CLIPS = 2000;
	const PAGE = 120; // pictures per "Show more"
	const list = new RecordingList();
	let loaded = $state(''); // what `list` holds: "<tab>:<camera>"
	let loading = $state(false);
	let failed = $state(false);
	let truncated = $state(false);
	let pictureLimit = $state(PAGE);

	let sequence = 0;
	async function load(view: Tab, cameraId: string, limit: number) {
		const key = `${view}:${cameraId}`;
		const mine = ++sequence;
		loading = true;
		failed = false;
		const data = await api
			.recordings({
				camera: cameraId || undefined,
				...(view === 'events'
					? { trigger: 'clips', limit: CLIPS }
					: view === 'continuous'
						? { trigger: 'continuous', limit: 500 }
						: { kind: 'picture', limit })
			})
			.catch(() => null);
		if (mine !== sequence) return; // the view or the filter changed meanwhile
		loading = false;
		if (!data) {
			failed = loaded !== key; // keep showing what there is when only a refresh failed
			return;
		}
		list.items = data.recordings;
		truncated = data.truncated;
		loaded = key;
	}

	$effect(() => {
		if (tab === 'timeline') return; // the timeline loads its own window
		const view = tab;
		const cameraId = camera;
		const limit = pictureLimit;
		load(view, cameraId, limit);
		// New recordings come in all the time: reload at most every 10 seconds.
		const kinds =
			view === 'pictures'
				? ['recording.picture', 'recording.deleted']
				: ['recording.finished', 'recording.deleted', 'recording.continuous'];
		let timer: ReturnType<typeof setTimeout> | undefined;
		const off = store.on((e) => {
			if (!kinds.includes(e.type)) return;
			timer ??= setTimeout(() => {
				timer = undefined;
				load(view, cameraId, limit);
			}, 10_000);
		});
		return () => {
			off();
			clearTimeout(timer);
		};
	});
	// Another camera or view starts at the first page of pictures again.
	$effect(() => {
		void tab;
		void camera;
		pictureLimit = PAGE;
	});

	const current = $derived(loaded === `${tab}:${camera}`);
	const items = $derived(current ? list.items : []);

	// --- Events
	const triggerCounts = $derived.by(() => {
		const counts = new Map<string, number>();
		if (tab === 'events')
			for (const r of items) counts.set(r.trigger, (counts.get(r.trigger) ?? 0) + 1);
		return [...counts].sort((a, b) => b[1] - a[1]);
	});
	const clips = $derived(trigger ? items.filter((r) => r.trigger === trigger) : items);
	const events = $derived(tab === 'events' ? groupEvents(clips) : []);
	const eventDays = $derived.by(() => {
		const days: [string, ClipEvent[]][] = [];
		for (const e of events) {
			const last = days.at(-1);
			if (last?.[0] === e.day) last[1].push(e);
			else days.push([e.day, [e]]);
		}
		return days;
	});
	let now = $state(Date.now());
	$effect(() => {
		const timer = setInterval(() => (now = Date.now()), 60_000);
		return () => clearInterval(timer);
	});
	let heatDays = $state<RecentDays>(readRecentDays());
	const heat = $derived(
		heatMap(
			clips,
			shownCameras.map((c) => c.id),
			now,
			heatDays
		)
	);

	let highlighted = $state<string | null>(null);
	let unhighlight: ReturnType<typeof setTimeout> | undefined;
	async function jump(cameraId: string, from: number, end: number) {
		const target = events.find((e) => e.camera === cameraId && e.start < end && e.end >= from);
		if (!target) return;
		await tick();
		document
			.getElementById(`event-${target.id}`)
			?.scrollIntoView({ behavior: 'smooth', block: 'center' });
		highlighted = target.id;
		clearTimeout(unhighlight);
		unhighlight = setTimeout(() => (highlighted = null), 2000);
	}

	// --- The other grids, by the browser's day, like the times on the tiles.
	const byDay = $derived.by(() => {
		const days: [string, Recording[]][] = [];
		for (const r of items) {
			const day = localDay(r.start);
			const last = days.at(-1);
			if (last?.[0] === day) last[1].push(r);
			else days.push([day, [r]]);
		}
		return days;
	});

	// --- The dialog
	let open = $state<Recording | null>(null);
	let playlist = $state<Recording[] | undefined>(undefined);
	let at = $state(0);
	function play(r: Recording, clipsOfEvent?: Recording[]) {
		playlist = clipsOfEvent;
		at = 0;
		open = r;
	}
	function changed(updated: Recording[]) {
		for (const r of updated) list.replace(r);
		if (playlist) {
			const byId = new Map(updated.map((r) => [r.id, r]));
			playlist = playlist.map((r) => byId.get(r.id) ?? r);
		}
	}
	function deleted(ids: string[]) {
		const gone = new Set(ids);
		list.items = list.items.filter((r) => !gone.has(r.id));
		if (playlist) playlist = playlist.filter((r) => !gone.has(r.id));
	}

	const continuousOn = $derived(store.cameras.some((c) => c.record === 'continuous'));
	const filtered = $derived(!!camera || !!trigger);
	const emptyWhere = $derived(camera ? ` from ${nameOf(camera)}` : '');
</script>

<svelte:head><title>Recordings · Norn</title></svelte:head>

<div class="mb-3 flex flex-wrap items-center gap-x-4 gap-y-3 sm:mb-4">
	<h1 class="mr-auto page-title">Recordings</h1>
	<!-- The views, the same width on every screen: no jumping when switching. -->
	<div
		class="grid w-full grid-cols-4 rounded-xl bg-surface-3 p-1 sm:w-auto"
		role="tablist"
		aria-label="View"
	>
		{#each TABS as t (t.id)}
			<button
				role="tab"
				id="tab-{t.id}"
				aria-selected={tab === t.id}
				aria-controls="view"
				class="flex items-center justify-center gap-1.5 rounded-lg px-2 py-1.5 text-sm font-medium transition sm:px-3 {tab ===
				t.id
					? 'bg-surface text-text shadow'
					: 'text-muted hover:text-text'}"
				onclick={() => navigate({ tab: t.id })}
				><t.icon class="hidden size-4 min-[440px]:block" />{t.label}</button
			>
		{/each}
	</div>
</div>

<!-- One row of filters for every view: it scrolls sideways rather than wrapping, so the page
     below never moves. -->
<div
	class="-mx-3 mb-4 flex [scrollbar-width:none] gap-2 overflow-x-auto px-3 py-0.5 sm:mx-0 sm:mb-5 sm:px-0"
	role="group"
	aria-label="Filters"
>
	<button
		class="chip shrink-0 {camera === '' ? 'chip-active' : ''}"
		aria-pressed={camera === ''}
		onclick={() => navigate({ camera: '' })}>All cameras</button
	>
	{#each store.cameras as c (c.id)}
		<button
			class="chip shrink-0 {camera === c.id ? 'chip-active' : ''}"
			aria-pressed={camera === c.id}
			onclick={() => navigate({ camera: camera === c.id ? '' : c.id })}>{c.name}</button
		>
	{/each}
	{#if tab === 'events' && triggerCounts.length > 1}
		<span class="mx-1 w-px shrink-0 self-stretch bg-line" aria-hidden="true"></span>
		{#each triggerCounts as [t, n] (t)}
			<button
				class="chip shrink-0 {trigger === t ? 'chip-active' : ''}"
				aria-pressed={trigger === t}
				onclick={() => navigate({ trigger: trigger === t ? '' : t })}
				><TriggerIcon trigger={t} />{triggerLabel(t)}<span class="text-muted tabular-nums">{n}</span
				></button
			>
		{/each}
	{/if}
</div>

<div id="view" role="tabpanel" aria-labelledby="tab-{tab}">
	{#if tab === 'timeline'}
		<Timeline
			cameras={shownCameras}
			onopen={(r, seconds) => {
				playlist = undefined;
				at = seconds;
				open = r;
			}}
		/>
	{:else if failed}
		<div class="mx-auto mt-10 max-w-md card px-8 py-12 text-center">
			<h2 class="text-lg font-semibold">The recordings didn't load</h2>
			<p class="mt-2 text-sm text-muted">Norn didn't answer. It may be restarting.</p>
			<button class="mt-6 btn-ghost" onclick={() => load(tab, camera, pictureLimit)}
				><RefreshCw class="size-4" />Try again</button
			>
		</div>
	{:else if !current}
		<!-- Loading: the shape of what comes, so nothing jumps. -->
		{#if tab === 'events'}
			<div class="space-y-4" aria-busy="true" aria-label="Loading">
				<div class="h-32 animate-pulse rounded-2xl bg-surface-2"></div>
				{#each Array(3) as _, i (i)}
					<div class="h-44 animate-pulse rounded-2xl bg-surface-2"></div>
				{/each}
			</div>
		{:else}
			<div
				class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 2xl:grid-cols-6"
				aria-busy="true"
				aria-label="Loading"
			>
				{#each Array(8) as _, i (i)}
					<div class="aspect-[4/3] animate-pulse rounded-2xl bg-surface-2"></div>
				{/each}
			</div>
		{/if}
	{:else if tab === 'events'}
		<div class="space-y-6">
			<HeatMap
				map={heat}
				{names}
				days={heatDays}
				onpick={jump}
				ondays={(d) => {
					heatDays = d;
					writeRecentDays(d);
				}}
			/>
			{#if truncated}
				<p class="rounded-xl bg-warning/10 px-4 py-3 text-sm text-warning">
					Showing the newest {CLIPS} clips. Pick a camera to see older ones, or use the timeline.
				</p>
			{/if}
			{#if !events.length}
				<div class="mx-auto max-w-md card px-8 py-12 text-center">
					<span
						class="mx-auto mb-5 grid size-14 place-items-center rounded-2xl bg-accent/15 text-accent"
						><Zap class="size-7" /></span
					>
					{#if filtered}
						<h2 class="text-lg font-semibold">
							No {trigger ? triggerLabel(trigger).toLowerCase() : ''} clips{emptyWhere}
						</h2>
						<p class="mt-2 text-sm text-muted">Other cameras or triggers may have some.</p>
						<button class="mt-6 btn-ghost" onclick={() => navigate({ camera: '', trigger: '' })}
							>Show all clips</button
						>
					{:else}
						<h2 class="text-lg font-semibold">No clips yet</h2>
						<p class="mt-2 text-sm text-muted">
							A clip records when a trigger fires (a person, motion, …) or when you record one by
							hand on a camera's page. What records, and when, is set on Triggers.
						</p>
						<a class="mt-6 btn-ghost" href="/triggers">Open Triggers</a>
					{/if}
				</div>
			{/if}
			{#each eventDays as [day, dayEvents] (day)}
				<section class="space-y-3" aria-label={formatDay(day)}>
					<h2 class="flex items-baseline gap-2">
						<span class="text-base font-semibold">{formatDay(day)}</span>
						<span class="text-xs text-muted">
							{dayEvents.length}
							{dayEvents.length === 1 ? 'event' : 'events'}
						</span>
					</h2>
					{#each dayEvents as event (event.id)}
						<EventCard
							{event}
							cameraName={nameOf(event.camera)}
							highlight={highlighted === event.id}
							onplay={play}
							onchanged={changed}
							ondeleted={deleted}
						/>
					{/each}
				</section>
			{/each}
		</div>
	{:else if !items.length}
		<div class="mx-auto mt-6 max-w-md card px-8 py-12 text-center">
			<span
				class="mx-auto mb-5 grid size-14 place-items-center rounded-2xl bg-accent/15 text-accent"
			>
				{#if tab === 'continuous'}<Video class="size-7" />{:else}<Image class="size-7" />{/if}
			</span>
			{#if tab === 'continuous'}
				<h2 class="text-lg font-semibold">No continuous recordings{emptyWhere}</h2>
				<p class="mt-2 text-sm text-muted">
					{#if !continuousOn}
						Continuous recording is off for every camera. Turn it on in a camera's recording
						settings: it then records all the time, in files of a few minutes.
					{:else}
						The first file appears here when it is finished.
					{/if}
				</p>
			{:else}
				<h2 class="text-lg font-semibold">No pictures{emptyWhere}</h2>
				<p class="mt-2 text-sm text-muted">
					Norn takes a picture on a timer when “Pictures every” is set on Triggers or for a camera.
				</p>
				<a class="mt-6 btn-ghost" href="/triggers">Open Triggers</a>
			{/if}
		</div>
	{:else}
		<div class="space-y-8">
			{#each byDay as [day, dayItems] (day)}
				<section aria-label={formatDay(day)}>
					<h2 class="mb-3 flex items-baseline gap-2">
						<span class="text-base font-semibold">{formatDay(day)}</span>
						<span class="text-xs text-muted">{dayItems.length}</span>
					</h2>
					<div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 2xl:grid-cols-6">
						{#each dayItems as r (r.id)}
							<RecordingTile
								recording={r}
								cameraName={camera ? undefined : nameOf(r.camera)}
								onopen={(x) => play(x, tab === 'pictures' ? items : undefined)}
								ondelete={list.remove}
								onpin={list.pin}
							/>
						{/each}
					</div>
				</section>
			{/each}
			{#if truncated}
				<div class="flex flex-col items-center gap-2 py-2 text-center">
					{#if tab === 'pictures'}
						<p class="text-sm text-muted">
							The newest {items.length} pictures. The timeline shows them all, along the hours.
						</p>
						<div class="flex gap-2">
							<button class="btn-ghost" disabled={loading} onclick={() => (pictureLimit += PAGE)}
								>Show more</button
							>
							<button class="btn-ghost" onclick={() => navigate({ tab: 'timeline' })}
								>Open the timeline</button
							>
						</div>
					{:else}
						<p class="text-sm text-muted">
							The newest {items.length}. Pick a camera, or use the timeline, to see older ones.
						</p>
					{/if}
				</div>
			{/if}
		</div>
	{/if}
</div>

<RecordingDialog
	bind:recording={open}
	{at}
	list={playlist}
	onchanged={(r) => changed([r])}
	ondeleted={(r) => deleted([r.id])}
/>
