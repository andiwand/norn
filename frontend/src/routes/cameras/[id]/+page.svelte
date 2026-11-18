<script lang="ts">
	// One camera: its video at its own shape, the switches used every day right under it, its
	// last 24 hours, and beside it (on phones, below) everything else in four tabs: Steer,
	// Settings, Recording, Device. The tab is in the URL (?tab=), so links can open one.
	import { tick } from 'svelte';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { api, urls, type Control, type Recording } from '#lib/api.js';
	import { store } from '#lib/state.svelte.js';
	import { readStoredJson, writeStored } from '#lib/stored.js';
	import { byGroup, cameraModel, triggerLabel } from '#lib/format.js';
	import LiveVideo from '#lib/components/LiveVideo.svelte';
	import PtzPad from '#lib/components/PtzPad.svelte';
	import ControlField from '#lib/components/ControlField.svelte';
	import QuickControls from '#lib/components/QuickControls.svelte';
	import DetectionOverlay from '#lib/components/DetectionOverlay.svelte';
	import CameraActivity from '#lib/components/CameraActivity.svelte';
	import RecordingDialog from '#lib/components/RecordingDialog.svelte';
	import EventBadge from '#lib/components/EventBadge.svelte';
	import RecBadge from '#lib/components/RecBadge.svelte';
	import RecordButton from '#lib/components/RecordButton.svelte';
	import CameraRecording from '#lib/components/CameraRecording.svelte';
	import CameraConnect from '#lib/components/CameraConnect.svelte';
	import DeviceCard from '#lib/components/DeviceCard.svelte';
	import NornPresets from '#lib/components/NornPresets.svelte';
	import PtzAutomation from '#lib/components/PtzAutomation.svelte';
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';
	import Pencil from '@lucide/svelte/icons/pencil';
	import ExternalLink from '@lucide/svelte/icons/external-link';
	import Volume2 from '@lucide/svelte/icons/volume-2';
	import VolumeX from '@lucide/svelte/icons/volume-x';
	import Maximize from '@lucide/svelte/icons/maximize';
	import Camera from '@lucide/svelte/icons/camera';
	import MapPin from '@lucide/svelte/icons/map-pin';
	import ScanEye from '@lucide/svelte/icons/scan-eye';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import CircleArrowUp from '@lucide/svelte/icons/circle-arrow-up';

	const id = $derived(page.params.id ?? '');
	const camera = $derived(store.camera(id));
	const caps = $derived(new Set(camera?.capabilities ?? []));

	let stream = $state('auto');
	let playing = $state('main');
	const qualityName = (id: string) => ({ main: 'HD', sub: 'SD', low: 'Low' })[id] ?? id;
	let muted = $state(true);
	let mode = $state<string | null>(null);
	let frame = $state<HTMLElement | null>(null);
	const controls = $derived(store.controls[id]?.controls ?? []);
	const presets = $derived(store.controls[id]?.presets ?? []);
	const enabled = $derived(camera?.enabled ?? false);
	const groups = $derived(byGroup(controls));
	let open = $state<Recording | null>(null);
	let openAt = $state(0); // seconds into it (from the timeline)
	let activity = $state<CameraActivity | null>(null);

	// Depends on the id and enabled only: the camera object is replaced on each refresh.
	$effect(() => {
		if (id && enabled) store.loadControls(id); // the cached ones show at once; this updates
	});

	// The picture's shape, from the newest still, remembered so the page doesn't jump next time.
	const ASPECTS = 'norn.aspects';
	let aspect = $state(16 / 9);
	$effect(() => {
		const cameraId = id;
		if (!cameraId) return;
		aspect = readStoredJson<Record<string, number>>(ASPECTS, {})[cameraId] ?? 16 / 9;
		const img = new Image();
		img.onload = () => {
			if (!img.naturalWidth || !img.naturalHeight) return;
			aspect = img.naturalWidth / img.naturalHeight;
			writeStored(ASPECTS, JSON.stringify({ ...readStoredJson(ASPECTS, {}), [cameraId]: aspect }));
		};
		img.src = urls.still(cameraId, 60);
	});

	// What Norn's AI sees, drawn on the video: only where it looks for objects. On by default.
	const SHOW_OBJECTS = 'norn.show-objects';
	let showObjects = $state(readStoredJson<boolean>(SHOW_OBJECTS, true));
	const nornObjects = $derived(
		(camera?.events?.norn ?? []).some((k) => ['person', 'vehicle', 'animal'].includes(k))
	);
	function toggleObjects() {
		showObjects = !showObjects;
		writeStored(SHOW_OBJECTS, JSON.stringify(showObjects));
	}

	// The tabs. Steer only for cameras that move.
	type Tab = 'steer' | 'settings' | 'recording' | 'device';
	const tabs = $derived(
		(
			[
				['steer', 'Steer'],
				['settings', 'Settings'],
				['recording', 'Recording'],
				['device', 'Device']
			] as [Tab, string][]
		).filter(([t]) => t !== 'steer' || caps.has('ptz'))
	);
	const tab = $derived.by<Tab>(() => {
		const wanted = page.url.searchParams.get('tab');
		return tabs.find(([t]) => t === wanted)?.[0] ?? tabs[0][0];
	});
	let tabBar = $state<HTMLElement | null>(null);

	async function show(next: Tab, { scroll = false, focus = false } = {}) {
		const url = new URL(page.url.href);
		if (next === tabs[0][0]) url.searchParams.delete('tab');
		else url.searchParams.set('tab', next);
		await goto(url, { replace: true, reset: false });
		await tick();
		if (focus) tabBar?.querySelector<HTMLElement>(`[data-tab="${next}"]`)?.focus();
		// The tabs out of view (on phones they are below the video, the activity below them):
		// bring them into view.
		const top = tabBar?.getBoundingClientRect().top ?? 0;
		if (scroll && tabBar && (top < 0 || top > innerHeight * 0.6))
			tabBar.scrollIntoView({ behavior: 'smooth', block: 'start' });
	}

	function onTabKey(e: KeyboardEvent) {
		const i = tabs.findIndex(([t]) => t === tab);
		const step = { ArrowRight: 1, ArrowLeft: -1, Home: -i, End: tabs.length - 1 - i }[e.key];
		if (step === undefined) return;
		e.preventDefault();
		show(tabs[(i + step + tabs.length) % tabs.length][0], { focus: true });
	}

	async function setControl(control: Control, value: unknown) {
		const previous = control.value;
		if (control.kind !== 'button') control.value = value;
		const ok = await store.attempt(() => api.setControl(id, control.id, value));
		if (ok === undefined && control.kind !== 'button') control.value = previous;
		else if (control.kind === 'button') store.toast(`${control.label} triggered`, 'success');
	}

	function fullscreen() {
		const el = frame as (HTMLElement & { webkitEnterFullscreen?: () => void }) | null;
		if (!el) return;
		if (document.fullscreenElement) document.exitFullscreen();
		else if (el.requestFullscreen) el.requestFullscreen();
		else
			(
				el.querySelector('video') as HTMLVideoElement & { webkitEnterFullscreen?: () => void }
			)?.webkitEnterFullscreen?.();
	}

	const modeLabel: Record<string, string> = {
		webrtc: 'WebRTC',
		mse: 'MSE',
		hls: 'HLS',
		mp4: 'MP4',
		mjpeg: 'MJPEG'
	};

	const online = $derived(camera?.device ? camera.device.online : !camera?.error);
	const recordingNow = $derived(
		!camera?.recording
			? 'Not recording'
			: camera.recording.mode === 'continuous'
				? 'Recording continuously'
				: `Recording${camera.recording.trigger ? ` · ${triggerLabel(camera.recording.trigger)}` : ''}`
	);
	const section = 'card';
	const sectionTitle = 'px-4 pt-4 pb-1 eyebrow';
</script>

<svelte:head><title>{camera?.name ?? 'Camera'} · Norn</title></svelte:head>

{#if !store.loaded}
	<div class="aspect-video animate-pulse rounded-2xl bg-surface-2"></div>
{:else if !camera}
	<div class="mx-auto mt-10 max-w-md card p-10 text-center">
		<h1 class="text-lg font-semibold">Camera not found</h1>
		<p class="mt-2 text-sm text-muted">There is no camera “{id}”.</p>
		<a href="/" class="mt-6 btn-ghost">Back to Live</a>
	</div>
{:else}
	<div class="mb-4 flex items-start gap-3">
		<a href="/" class="-ml-2 icon-btn shrink-0" aria-label="Back to Live"
			><ArrowLeft class="size-5" /></a
		>
		<div class="min-w-0 flex-1">
			<h1 class="truncate text-xl leading-9 font-semibold tracking-tight">{camera.name}</h1>
			<!-- What it is and what it does now, at a glance. -->
			<p class="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-muted">
				<span class="flex items-center gap-1.5">
					<span class="size-1.5 rounded-full {online ? 'bg-success' : 'bg-danger'}"></span>
					{camera.enabled ? (online ? 'Online' : 'Offline') : 'Disabled'}
				</span>
				<span>{cameraModel(camera)}</span>
				<span class={camera.recording ? 'font-medium text-danger' : ''}>{recordingNow}</span>
				{#if camera.firmware?.status === 'update'}
					<button
						class="flex items-center gap-1 font-medium text-accent hover:underline"
						onclick={() => show('device', { scroll: true })}
						><CircleArrowUp class="size-3.5" />Firmware update</button
					>
				{/if}
			</p>
		</div>
		{#if camera.web_url}
			<a
				href={camera.web_url}
				target="_blank"
				rel="noopener noreferrer"
				class="btn-ghost shrink-0"
				title="The camera's own web page"
				aria-label="The camera's own web page"
				><ExternalLink class="size-4" /><span class="hidden sm:inline">Camera page</span></a
			>
		{/if}
		<a
			href="/cameras/{camera.id}/edit"
			class="btn-ghost shrink-0"
			title="Name, address, password, streams"
			aria-label="Edit the camera"
			><Pencil class="size-4" /><span class="hidden sm:inline">Edit</span></a
		>
	</div>

	{#if camera.error}
		<div
			class="mb-4 flex items-center gap-3 rounded-2xl bg-warning/10 px-4 py-3 text-sm text-warning"
		>
			<TriangleAlert class="size-4 shrink-0" />{camera.error}
		</div>
	{/if}

	<!-- Wide screens: the video and the activity on the left, the tabs beside them. Phones: the
	     video, the tabs (what's done with the camera), then the activity. -->
	<div
		class="grid items-start gap-x-6 gap-y-4 lg:grid-cols-[minmax(0,1fr)_24rem] lg:grid-rows-[auto_1fr]"
	>
		<div class="min-w-0 space-y-4 lg:col-start-1 lg:row-start-1">
			<!-- The video at its own shape (4:3 has no black bars), never taller than the screen. -->
			<div
				bind:this={frame}
				data-ptz-keys
				class="group relative mx-auto w-full overflow-hidden rounded-2xl border border-line bg-black shadow-[0_30px_80px_-40px_rgb(0_0_0/0.9)] lg:w-[min(100%,calc((100dvh_-_13rem)*var(--aspect)))]"
				style="aspect-ratio:{aspect};--aspect:{aspect}"
			>
				{#if camera.enabled && caps.has('live')}
					{#key stream}
						<LiveVideo
							camera={camera.id}
							stream={stream === 'auto' ? 'main' : stream}
							codec={camera.streams.find((s) => s.id === stream)?.codec}
							ladder={stream === 'auto' ? camera.streams : undefined}
							bind:playing
							{muted}
							bind:mode
							class="h-full w-full"
						/>
					{/key}
					{#if nornObjects && showObjects}<DetectionOverlay camera={camera.id} />{/if}
				{:else}
					<div class="grid h-full place-items-center text-sm text-white/60">
						{camera.enabled ? 'No stream' : 'This camera is disabled'}
					</div>
				{/if}

				<RecordButton {camera} class="absolute top-3 right-3" />
				<div
					class="absolute top-3 left-3 flex max-w-[calc(100%-6rem)] flex-wrap items-center gap-2"
				>
					{#if camera.recording}<RecBadge mode={camera.recording.mode} />{/if}
					{#if camera.events}<EventBadge active={camera.events.active} />{/if}
					{#if mode}
						<span
							class="rounded-full bg-black/50 px-2.5 py-1 text-[11px] font-medium text-white/85 backdrop-blur-md"
						>
							{modeLabel[mode] ?? mode}
						</span>
					{/if}
				</div>

				<div
					class="absolute inset-x-0 bottom-0 flex items-center gap-2 bg-gradient-to-t from-black/70 to-transparent p-3 pt-12 transition md:opacity-0 md:group-hover:opacity-100 md:focus-within:opacity-100"
				>
					<!-- MJPEG has no sound: no mute button for it. -->
					{#if camera.streams.find((s) => s.id === playing)?.codec !== 'mjpeg'}
						<button
							class="glass-btn"
							onclick={() => (muted = !muted)}
							aria-label={muted ? 'Unmute' : 'Mute'}
							title={muted ? 'Unmute' : 'Mute'}
						>
							{#if muted}<VolumeX class="size-4" />{:else}<Volume2 class="size-4" />{/if}
						</button>
					{/if}
					{#if camera.streams.length > 1}
						<!-- Narrow screens: a dropdown; there's no room for every quality. -->
						<select
							class="rounded-full border-0 bg-black/45 px-3 py-1 text-xs font-medium text-white backdrop-blur-md sm:hidden"
							value={stream}
							onchange={(e) => (stream = e.currentTarget.value)}
							aria-label="Quality"
						>
							<option value="auto">Auto · {qualityName(playing)}</option>
							{#each camera.streams as s (s.id)}
								<option value={s.id}>{qualityName(s.id)}</option>
							{/each}
						</select>
						<div class="hidden rounded-full bg-black/45 p-1 backdrop-blur-md sm:flex">
							{#each [{ id: 'auto', transcoded: false }, ...camera.streams] as s (s.id)}
								<button
									class="rounded-full px-3 py-1 text-xs font-medium transition {stream === s.id
										? 'bg-white text-black'
										: 'text-white/80 hover:text-white'}"
									title={s.id === 'auto'
										? `Adapts to the connection; now ${qualityName(playing)}`
										: s.transcoded
											? 'Made small by Norn, for weak connections'
											: ''}
									onclick={() => (stream = s.id)}
								>
									{s.id === 'auto' ? `Auto · ${qualityName(playing)}` : qualityName(s.id)}
								</button>
							{/each}
						</div>
					{/if}
					<div class="ml-auto flex gap-2">
						{#if nornObjects && camera.enabled}
							<button
								class="glass-btn {showObjects ? 'text-warning' : ''}"
								onclick={toggleObjects}
								aria-pressed={showObjects}
								aria-label="Show what Norn's AI sees"
								title={showObjects
									? "Hide what Norn's AI sees"
									: "Show what Norn's AI sees: a box around each person, vehicle or animal"}
								><ScanEye class="size-4" /></button
							>
						{/if}
						{#if caps.has('snapshot')}
							<a
								class="glass-btn"
								href={urls.snapshot(camera.id)}
								download="{camera.id}.jpg"
								aria-label="Save a snapshot"
								title="Save a snapshot"
							>
								<Camera class="size-4" />
							</a>
						{/if}
						<button
							class="glass-btn"
							onclick={fullscreen}
							aria-label="Fullscreen"
							title="Fullscreen"><Maximize class="size-4" /></button
						>
					</div>
				</div>
			</div>

			{#if camera.enabled}
				<QuickControls {controls} onchange={setControl} />
			{/if}
		</div>

		<!-- The tabs: beside the video (they stay in view while it plays); on phones below it, the
		     tab bar sticking under the header. All tabs stay mounted: an unsaved form in one
		     survives a look at another. -->
		<aside
			class="min-w-0 lg:sticky lg:top-20 lg:col-start-2 lg:row-span-2 lg:row-start-1 lg:max-h-[calc(100dvh-6rem)] lg:overflow-y-auto lg:overscroll-contain lg:rounded-2xl"
		>
			<div
				bind:this={tabBar}
				class="sticky top-12 z-10 -mx-3 scroll-mt-12 bg-bg/90 px-3 py-2 backdrop-blur-xl sm:-mx-6 sm:px-6 md:top-14 md:scroll-mt-14 lg:top-0 lg:mx-0 lg:px-0 lg:pt-0"
			>
				<div
					class="flex rounded-xl border border-line bg-surface-2 p-1"
					role="tablist"
					aria-label="About this camera"
					tabindex="-1"
					onkeydown={onTabKey}
				>
					{#each tabs as [t, label] (t)}
						<button
							role="tab"
							id="tab-{t}"
							data-tab={t}
							aria-selected={tab === t}
							aria-controls="panel-{t}"
							tabindex={tab === t ? 0 : -1}
							class="h-9 flex-1 rounded-lg px-2 text-sm font-medium transition {tab === t
								? 'bg-surface text-text shadow'
								: 'text-muted hover:text-text'}"
							onclick={() => show(t)}>{label}</button
						>
					{/each}
				</div>
			</div>

			<div class="space-y-4 pt-2 lg:pb-1">
				{#if caps.has('ptz')}
					<div
						id="panel-steer"
						role="tabpanel"
						aria-labelledby="tab-steer"
						hidden={tab !== 'steer'}
						class="space-y-4"
					>
						<section class="{section} p-4">
							<PtzPad camera={camera.id} zoom={caps.has('zoom')} />
							<p class="mt-3 text-center text-xs text-muted">
								Hold an arrow to move. With the mouse over the video, the arrow keys work too{caps.has(
									'zoom'
								)
									? ', and + and − zoom'
									: ''}.
							</p>
							{#if presets.length}
								<h3 class="mt-5 mb-2 text-xs font-medium text-muted">The camera's presets</h3>
								<div class="flex flex-wrap gap-2">
									{#each presets as preset (preset.id)}
										<button
											class="chip h-9"
											onclick={() =>
												store.attempt(
													() => api.ptz(id, { action: 'goto', preset: preset.id }),
													`Going to “${preset.name}”`
												)}
										>
											<MapPin class="size-3.5" />{preset.name}
										</button>
									{/each}
								</div>
							{/if}
							<NornPresets {camera} {controls} />
						</section>
						<section class={section}>
							<h2 class={sectionTitle}>Patrol & following</h2>
							<div class="px-4 pb-4">
								{#key camera.id}<PtzAutomation {camera} />{/key}
							</div>
						</section>
					</div>
				{/if}

				<div
					id="panel-settings"
					role="tabpanel"
					aria-labelledby="tab-settings"
					hidden={tab !== 'settings'}
					class="space-y-4"
				>
					{#each groups as [group, items] (group)}
						<section class={section}>
							<h2 class={sectionTitle}>{group}</h2>
							<div class="divide-y divide-line px-4 pb-2">
								{#each items as control (control.id)}
									<div class="py-2">
										<ControlField {control} onchange={(v) => setControl(control, v)} />
									</div>
								{/each}
							</div>
						</section>
					{:else}
						<section class="{section} p-5 text-sm text-muted">
							{#if !camera.enabled}
								This camera is disabled.
							{:else if caps.has('controls')}
								Loading the camera's settings…
							{:else}
								Norn can't change settings of this camera.{#if camera.web_url}
									Its own page may: <a
										href={camera.web_url}
										target="_blank"
										rel="noopener noreferrer"
										class="text-accent hover:underline">open it</a
									>.{/if}
							{/if}
						</section>
					{/each}
				</div>

				<div
					id="panel-recording"
					role="tabpanel"
					aria-labelledby="tab-recording"
					hidden={tab !== 'recording'}
				>
					<section class={section}>
						<h2 class={sectionTitle}>Recording & detection</h2>
						<div class="px-4 pb-4">
							<!-- Anew for another camera, or when presets come or go. -->
							{#key `${camera.id}:${Object.keys(camera.presets_norn ?? {}).join()}`}
								<CameraRecording {camera} />
							{/key}
						</div>
					</section>
				</div>

				<div
					id="panel-device"
					role="tabpanel"
					aria-labelledby="tab-device"
					hidden={tab !== 'device'}
					class="space-y-4"
				>
					<DeviceCard {camera} />
					<section class={section}>
						<h2 class={sectionTitle}>Connect</h2>
						<div class="px-4 pb-4"><CameraConnect {camera} {controls} /></div>
					</section>
					<a
						href="/cameras/{camera.id}/edit"
						class="flex items-center gap-3 card px-4 py-3 text-sm hover:bg-surface-2"
					>
						<Pencil class="size-4 text-muted" />
						<span class="flex-1">
							<span class="block font-medium">Edit the camera</span>
							<span class="block text-xs text-muted">Name, address, password, streams</span>
						</span>
					</a>
				</div>
			</div>
		</aside>

		<div class="min-w-0 lg:col-start-1 lg:row-start-2">
			<CameraActivity
				bind:this={activity}
				{camera}
				onopen={(r, at = 0) => {
					openAt = at;
					open = r;
				}}
				onsettings={() => show('recording', { scroll: true })}
			/>
		</div>
	</div>

	<RecordingDialog bind:recording={open} at={openAt} onchanged={(r) => activity?.replace(r)} />
{/if}
