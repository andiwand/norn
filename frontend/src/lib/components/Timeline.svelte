<script lang="ts">
	// All recordings on one time axis: a row per camera, a strip of thumbnails above it.
	// Drag to move in time, pick a scale, click a recording (or a point in a video) to open it.
	import { api, urls, type Camera, type Recording } from '../api';
	import { store } from '../state.svelte';
	import ChevronLeft from '@lucide/svelte/icons/chevron-left';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import Film from '@lucide/svelte/icons/film';
	import TriggerIcon from './TriggerIcon.svelte';
	import { triggerLabel } from '../format';

	let {
		cameras,
		onopen
	}: {
		cameras: Camera[];
		/** Open a recording, `at` seconds into it. */
		onopen: (r: Recording, at: number) => void;
	} = $props();

	const HOUR = 3_600_000;
	const SCALES = [
		{ label: '1 h', span: HOUR },
		{ label: '6 h', span: 6 * HOUR },
		{ label: 'Day', span: 24 * HOUR },
		{ label: 'Week', span: 7 * 24 * HOUR }
	];
	// Tick steps in minutes; the first that gives at most about 8 labels.
	const STEPS = [5, 15, 30, 60, 180, 360, 720, 1440, 2880];
	const PICTURES = 600; // the server thins pictures to about this many per camera and request
	const BUCKETS = 400; // picture marks per row: more would not show anyway

	interface Item {
		r: Recording;
		t: number;
		end: number;
	}

	let span = $state(6 * HOUR);
	let end = $state(Date.now()); // the right edge of the window
	let following = $state(true); // the window moves with the clock
	let items = $state.raw<Item[]>([]);
	let truncated = $state(false);
	let loading = $state(false);
	let width = $state(800);
	let hover = $state<{ x: number; t: number } | null>(null);
	let dragging = $state(false);

	const start = $derived(end - span);
	const x = (t: number) => ((t - start) / span) * 100; // percent from the left
	const timeAt = (fraction: number) => start + fraction * span;
	const cameraKey = $derived(cameras.map((c) => c.id).join(','));

	// Loading: one span either side of the window, so drags rarely need a new request. Only the
	// newest request counts; one already on its way for the same range isn't sent twice.
	type Range = { from: number; to: number; key: string };
	let loaded: Range = { from: 0, to: 0, key: '' };
	let pending: Range | null = null;
	let sequence = 0;
	let failed = 0;

	const covers = (r: Range | null, from: number, to: number, key: string) =>
		!!r && r.key === key && from >= r.from && to <= r.to;

	async function load(force = false) {
		const key = cameraKey;
		if (!force && (covers(loaded, start, end, key) || covers(pending, start, end, key))) return;
		if (!force && Date.now() - failed < 5000) return; // don't hammer a server that fails
		const range = { from: start - span, to: end + span, key };
		pending = range;
		const mine = ++sequence;
		loading = true;
		const data = await api
			.recordings({
				camera: cameras.length === 1 ? cameras[0].id : undefined,
				since: new Date(range.from).toISOString(),
				until: new Date(range.to).toISOString(),
				limit: 20000,
				pictures: PICTURES
			})
			.catch(() => null);
		if (mine !== sequence) return; // a newer request answers instead
		pending = null;
		loading = false;
		if (!data) {
			failed = Date.now();
			return;
		}
		loaded = range;
		truncated = data.truncated;
		items = data.recordings.map((r) => {
			const t = new Date(r.start).getTime();
			return { r, t, end: t + (r.duration ?? 0) * 1000 };
		});
	}

	// Load when the window or the cameras change; while dragging, once the drag pauses.
	$effect(() => {
		void start;
		void cameraKey;
		const timer = setTimeout(() => load(), 150);
		return () => clearTimeout(timer);
	});

	// New recordings: reload, at most every 10 seconds, and only while the window shows now.
	$effect(() => {
		let timer: ReturnType<typeof setTimeout> | undefined;
		let last = 0;
		const off = store.on((e) => {
			const deleted = e.type === 'recording.deleted';
			if (!deleted && !(following && e.type.startsWith('recording.'))) return;
			if (!['recording.finished', 'recording.deleted', 'recording.picture'].includes(e.type))
				return;
			if (timer) return;
			timer = setTimeout(
				() => {
					timer = undefined;
					last = Date.now();
					load(true);
				},
				Math.max(1500, 10_000 - (Date.now() - last))
			);
		});
		const tick = setInterval(() => {
			if (following && !dragging) end = Date.now();
		}, 30_000);
		return () => {
			off();
			clearTimeout(timer);
			clearInterval(tick);
		};
	});

	// What a clip saw: its trigger, and what else was detected while it ran.
	const kindsOf = (r: Recording): string[] => {
		const extra = Array.isArray(r.meta?.events) ? (r.meta.events as string[]) : [];
		return [...new Set([r.trigger, ...extra])];
	};
	// Look for a detection: only the clips that saw it (none of the continuous files, pictures).
	let lookFor = $state('');
	const seenKinds = $derived(
		store.labels.filter((l) =>
			items.some((i) => i.r.kind === 'video' && kindsOf(i.r).includes(l.id))
		)
	);
	const matches = (i: Item) => !lookFor || (i.r.kind === 'video' && kindsOf(i.r).includes(lookFor));

	const rows = $derived(
		cameras.map((camera) => {
			const own = items.filter(
				(i) => i.r.camera === camera.id && i.end >= start && i.t <= end && matches(i)
			);
			// Pictures as one mark per bucket: thousands of marks would show the same few pixels.
			const marks = new Set<number>();
			for (const i of own) {
				if (i.r.kind === 'picture') marks.add(Math.round((x(i.t) / 100) * BUCKETS));
			}
			return {
				camera,
				videos: own.filter((i) => i.r.kind === 'video'),
				pictures: own.filter((i) => i.r.kind === 'picture'),
				marks: [...marks].map((b) => (b / BUCKETS) * 100)
			};
		})
	);

	// The thumbnail strip: for each slot, the picture or video thumbnail nearest its middle.
	// It holds still while dragging, so a drag doesn't download a stream of images.
	const slots = $derived(Math.max(3, Math.min(12, Math.floor(width / 150))));
	let stripStart = $state(Date.now() - 6 * HOUR);
	$effect(() => {
		if (!dragging) stripStart = start;
	});
	const strip = $derived.by(() => {
		const keys = new Set(cameras.map((c) => c.id));
		const withImages = items.filter((i) => i.r.thumbnail && keys.has(i.r.camera) && matches(i));
		return Array.from({ length: slots }, (_, n) => {
			const middle = stripStart + ((n + 0.5) / slots) * span;
			const half = span / slots / 2;
			let best: Item | null = null;
			for (const i of withImages) {
				const d = Math.abs(i.t - middle);
				if (d <= half && (!best || d < Math.abs(best.t - middle))) best = i;
			}
			return best;
		});
	});

	// Tick marks on the local clock, counted in calendar steps, so they stay on round times
	// across a change to or from summer time.
	const ticks = $derived.by(() => {
		const step = STEPS.find((m) => span / (m * 60_000) <= 8) ?? STEPS[STEPS.length - 1];
		const d = new Date(start);
		const advance = () => {
			if (step >= 1440) d.setDate(d.getDate() + step / 1440);
			else if (step >= 60) d.setHours(d.getHours() + step / 60);
			else d.setMinutes(d.getMinutes() + step);
		};
		if (step >= 1440) d.setHours(0, 0, 0, 0);
		else if (step >= 60) {
			d.setMinutes(0, 0, 0);
			d.setHours(Math.floor(d.getHours() / (step / 60)) * (step / 60));
		} else {
			d.setSeconds(0, 0);
			d.setMinutes(Math.floor(d.getMinutes() / step) * step);
		}
		const list: number[] = [];
		while (d.getTime() <= end && list.length < 50) {
			if (d.getTime() >= start) list.push(d.getTime());
			advance();
		}
		return { list, step };
	});

	function tickLabel(at: number, step: number): string {
		const d = new Date(at);
		const midnight = d.getHours() === 0 && d.getMinutes() === 0;
		if (step >= 1440 || midnight) {
			return d.toLocaleDateString([], { weekday: 'short', day: 'numeric' });
		}
		return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
	}

	function formatAt(ms: number): string {
		return new Date(ms).toLocaleString([], {
			weekday: 'short',
			hour: '2-digit',
			minute: '2-digit',
			second: span <= HOUR ? '2-digit' : undefined
		});
	}

	const title = $derived.by(() => {
		const day = (ms: number) =>
			new Date(ms).toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' });
		return day(start) === day(end) ? day(start) : `${day(start)} – ${day(end)}`;
	});

	function move(by: number) {
		end = Math.min(Date.now(), end + by);
		following = end >= Date.now() - 1000;
	}

	function setScale(next: number) {
		// Following the clock: stay at now. Else zoom around the middle of the window.
		const middle = end - span / 2;
		span = next;
		end = following ? Date.now() : Math.min(Date.now(), middle + next / 2);
		following = end >= Date.now() - 1000;
	}

	function now() {
		end = Date.now();
		following = true;
	}

	// Dragging a track moves the window; a click without dragging opens what is under it.
	let drag: { x: number; end: number; width: number; moved: boolean } | null = null;

	function down(e: PointerEvent) {
		if (e.button !== 0) return;
		const track = e.currentTarget as HTMLElement;
		track.setPointerCapture(e.pointerId);
		drag = { x: e.clientX, end, width: track.clientWidth, moved: false };
	}

	function moveTo(e: PointerEvent) {
		const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
		const fraction = (e.clientX - rect.left) / rect.width;
		hover = { x: fraction * 100, t: timeAt(fraction) };
		if (!drag) return;
		const dx = e.clientX - drag.x;
		if (Math.abs(dx) > 4) drag.moved = dragging = true;
		if (drag.moved) {
			end = Math.min(Date.now(), drag.end - (dx / drag.width) * span);
			following = end >= Date.now() - 1000;
		}
	}

	function up(e: PointerEvent, camera: string) {
		const started = drag;
		drag = null;
		dragging = false;
		// Only a press that started here, didn't move and used the main button opens something.
		if (!started || started.moved || e.button !== 0) return;
		const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
		openAt(camera, timeAt((e.clientX - rect.left) / rect.width));
	}

	function cancel() {
		drag = null;
		dragging = false;
	}

	/** Open the video playing at `at`, else the nearest picture or video close by. */
	function openAt(camera: string, at: number) {
		const row = rows.find((r) => r.camera.id === camera);
		if (!row) return;
		const video = row.videos.find((i) => i.t <= at && at <= Math.max(i.end, i.t + 1000));
		if (video) {
			onopen(video.r, Math.max(0, (at - video.t) / 1000));
			return;
		}
		const near = span / 60; // a few pixels either way
		let best: Item | null = null;
		let distance = Infinity;
		for (const i of [...row.pictures, ...row.videos]) {
			const d = Math.min(Math.abs(i.t - at), Math.abs(i.end - at));
			if (d < distance && d <= near) {
				best = i;
				distance = d;
			}
		}
		if (best) onopen(best.r, 0);
	}
</script>

<div class="card p-4 sm:p-5">
	<div class="mb-4 flex flex-wrap items-center gap-2">
		<div class="flex items-center gap-1">
			<button class="icon-btn size-9" onclick={() => move(-span / 2)} aria-label="Earlier"
				><ChevronLeft class="size-5" /></button
			>
			<button
				class="icon-btn size-9"
				onclick={() => move(span / 2)}
				disabled={following}
				aria-label="Later"><ChevronRight class="size-5" /></button
			>
		</div>
		<span class="min-w-0 text-sm font-semibold">{title}</span>
		{#if loading}<span class="text-xs text-muted">Loading…</span>{/if}
		{#if truncated}
			<span class="text-xs text-warning" title="Pick a shorter scale to see all of them"
				>Too many to show all</span
			>
		{/if}
		<div class="ml-auto flex items-center gap-2">
			<div class="flex rounded-xl bg-surface-3 p-1" role="radiogroup" aria-label="Scale">
				{#each SCALES as scale (scale.span)}
					<button
						role="radio"
						aria-checked={span === scale.span}
						class="rounded-lg px-2.5 py-1 text-xs font-medium whitespace-nowrap transition {span ===
						scale.span
							? 'bg-surface text-text shadow'
							: 'text-muted hover:text-text'}"
						onclick={() => setScale(scale.span)}>{scale.label}</button
					>
				{/each}
			</div>
			<button class="chip {following ? 'chip-active' : ''}" onclick={now}>Now</button>
		</div>
	</div>

	{#if seenKinds.length}
		<!-- Look for what was detected. -->
		<div class="mb-3 flex flex-wrap items-center gap-1.5">
			<button class="chip h-7 {lookFor === '' ? 'chip-active' : ''}" onclick={() => (lookFor = '')}
				>All</button
			>
			{#each seenKinds as label (label.id)}
				<button
					class="chip h-7 {lookFor === label.id ? 'chip-active' : ''}"
					onclick={() => (lookFor = lookFor === label.id ? '' : label.id)}
					><TriggerIcon trigger={label.id} />{label.name}</button
				>
			{/each}
		</div>
	{/if}

	<!-- Thumbnails along the window -->
	<div
		class="mb-3 grid gap-1.5"
		style:grid-template-columns="repeat({slots}, minmax(0, 1fr))"
		bind:clientWidth={width}
	>
		{#each strip as slot, n (n)}
			{#if slot}
				{@const r = slot.r}
				<button
					class="group relative aspect-video overflow-hidden rounded-lg bg-surface-2"
					onclick={() => onopen(r, 0)}
					title="{store.camera(r.camera)?.name ?? r.camera} · {formatAt(slot.t)}"
				>
					<img
						src={urls.small(r)}
						alt=""
						loading="lazy"
						class="h-full w-full object-cover transition group-hover:scale-105"
					/>
					<span
						class="absolute bottom-1 left-1 rounded bg-black/60 px-1 text-[10px] font-medium text-white tabular-nums"
						>{new Date(slot.t).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span
					>
				</button>
			{:else}
				<div class="grid aspect-video place-items-center rounded-lg bg-surface-2/50 text-muted/40">
					<Film class="size-4" />
				</div>
			{/if}
		{/each}
	</div>

	<!-- One track per camera -->
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="relative" onpointerleave={() => (hover = null)}>
		{#each rows as row (row.camera.id)}
			<div class="flex items-center gap-3 py-1">
				<span class="w-24 shrink-0 truncate text-xs font-medium sm:w-32" title={row.camera.name}
					>{row.camera.name}</span
				>
				<!-- svelte-ignore a11y_no_static_element_interactions -->
				<div
					class="relative h-8 flex-1 cursor-grab touch-pan-y overflow-hidden rounded-lg bg-surface-2 active:cursor-grabbing"
					onpointerdown={down}
					onpointermove={moveTo}
					onpointerup={(e) => up(e, row.camera.id)}
					onpointercancel={cancel}
				>
					{#each ticks.list as at (at)}
						<span class="absolute inset-y-0 w-px bg-line" style:left="{x(at)}%"></span>
					{/each}
					{#each row.videos as i (i.r.id)}
						<span
							class="absolute inset-y-1.5 rounded-[3px] {i.r.trigger === 'continuous'
								? 'bg-accent/35'
								: 'bg-accent'}"
							style:left="{Math.max(0, x(i.t))}%"
							style:width="max(3px, {Math.min(100, x(i.end)) - Math.max(0, x(i.t))}%)"
							title="{kindsOf(i.r).map(triggerLabel).join(', ')} · {formatAt(i.t)}"
						></span>
					{/each}
					<!-- What started each clip, as an icon on top of it. -->
					{#each row.videos.filter((i) => i.r.trigger !== 'continuous') as i (i.r.id)}
						<span
							class="pointer-events-none absolute top-1/2 z-[1] grid size-5 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full bg-surface text-accent shadow ring-1 ring-accent/40"
							style:left="{Math.min(98, Math.max(2, x(i.t)))}%"
						>
							<TriggerIcon
								trigger={kindsOf(i.r).find((k) => k !== 'motion') ?? i.r.trigger}
								class="size-3"
							/>
						</span>
					{/each}
					{#each row.marks as left (left)}
						<span class="absolute inset-y-2.5 w-[2px] rounded-full bg-accent-2" style:left="{left}%"
						></span>
					{/each}
					{#if hover}
						<span
							class="pointer-events-none absolute inset-y-0 w-px bg-text/70"
							style:left="{hover.x}%"
						></span>
					{/if}
				</div>
			</div>
		{/each}

		<!-- The axis -->
		<div class="flex gap-3">
			<span class="w-24 shrink-0 sm:w-32"></span>
			<div class="relative h-6 flex-1">
				{#each ticks.list as at (at)}
					<span
						class="absolute top-1 -translate-x-1/2 text-[10px] whitespace-nowrap text-muted tabular-nums"
						style:left="{x(at)}%">{tickLabel(at, ticks.step)}</span
					>
				{/each}
				{#if hover}
					<span
						class="absolute top-0 z-10 -translate-x-1/2 rounded-md bg-text px-1.5 py-0.5 text-[10px] font-medium whitespace-nowrap text-bg tabular-nums"
						style:left="clamp(2.5rem, {hover.x}%, calc(100% - 2.5rem))">{formatAt(hover.t)}</span
					>
				{/if}
			</div>
		</div>
	</div>

	<div class="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
		<span class="flex items-center gap-1.5"
			><span class="h-2 w-4 rounded-sm bg-accent"></span>Clip</span
		>
		<span class="flex items-center gap-1.5"
			><span class="h-2 w-4 rounded-sm bg-accent/35"></span>Continuous</span
		>
		<span class="flex items-center gap-1.5"
			><span class="h-3 w-[2px] rounded-full bg-accent-2"></span>Picture</span
		>
		<span class="ml-auto hidden sm:inline"
			>Drag to move in time · click to open · the grid lists them for the keyboard</span
		>
	</div>
</div>
