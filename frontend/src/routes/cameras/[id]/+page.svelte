<script lang="ts">
	import EventBadge from '#lib/components/EventBadge.svelte';
	import { page } from '$app/state';
	import { api, urls, type Control, type Recording } from '#lib/api.js';
	import { store } from '#lib/state.svelte.js';
	import { ownSettings } from '#lib/format.js';
	import LiveVideo from '#lib/components/LiveVideo.svelte';
	import PtzPad from '#lib/components/PtzPad.svelte';
	import ControlField from '#lib/components/ControlField.svelte';
	import RecordingTile from '#lib/components/RecordingTile.svelte';
	import RecordingDialog from '#lib/components/RecordingDialog.svelte';
	import RecBadge from '#lib/components/RecBadge.svelte';
	import RecordButton from '#lib/components/RecordButton.svelte';
	import CameraRecording from '#lib/components/CameraRecording.svelte';
	import CameraConnect from '#lib/components/CameraConnect.svelte';
	import DeviceCard from '#lib/components/DeviceCard.svelte';
	import Panel from '#lib/components/Panel.svelte';
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
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';

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
	const presetsOwn = $derived(
		Object.values(camera?.presets_norn ?? {}).filter((p) => ownSettings(p).length).length
	);
	const enabled = $derived(camera?.enabled ?? false);
	let recent = $state<Recording[]>([]);
	let open = $state<Recording | null>(null);

	const groups = $derived(
		Object.entries(
			controls.reduce<Record<string, Control[]>>((acc, c) => {
				(acc[c.group] ??= []).push(c);
				return acc;
			}, {})
		)
	);

	async function loadRecent(cameraId: string) {
		recent =
			// Videos: with pictures on a timer, the newest eight would all be pictures.
			(await api.recordings({ camera: cameraId, limit: 8, kind: 'video' }).catch(() => null))
				?.recordings ?? [];
	}

	// Depends on the id and enabled only: the camera object is replaced on each refresh.
	$effect(() => {
		if (!id || !enabled) return;
		const cameraId = id;
		store.loadControls(cameraId); // shows the cached controls at once; this updates them
		loadRecent(cameraId);
		return store.on((event) => {
			if (event.data.camera !== cameraId) return;
			if (event.type === 'recording.finished' || event.type === 'recording.deleted')
				loadRecent(cameraId);
		});
	});

	// The lifetime rings on the recent recordings count down.
	let ringNow = $state(Date.now());
	$effect(() => {
		const timer = setInterval(() => (ringNow = Date.now()), 60_000);
		return () => clearInterval(timer);
	});

	async function pin(r: Recording, pinned: boolean) {
		const updated = await store.pin(r, pinned);
		if (updated) replace(updated);
	}

	function replace(updated: Recording) {
		recent = recent.map((x) => (x.id === updated.id ? updated : x));
	}

	async function remove(r: Recording) {
		const ok = await store.attempt(async () => {
			await api.deleteRecording(r.id);
			return true;
		}, 'Recording deleted');
		if (ok) recent = recent.filter((x) => x.id !== r.id);
	}

	async function setControl(control: Control, value: unknown) {
		const previous = control.value;
		if (control.kind !== 'button') control.value = value;
		const ok = await store.attempt(() => api.setControl(id, control.id, value).then(() => true));
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
	<div class="mb-5 flex items-center gap-3">
		<a href="/" class="-ml-2 icon-btn" aria-label="Back"><ArrowLeft class="size-5" /></a>
		<div class="min-w-0 flex-1">
			<h1 class="truncate text-xl font-semibold tracking-tight">{camera.name}</h1>
			<p class="text-xs text-muted">{camera.driver} · {camera.id}</p>
		</div>
		{#if camera.web_url}
			<a
				href={camera.web_url}
				target="_blank"
				rel="noopener noreferrer"
				class="btn-ghost"
				title="The camera's own web page"
				><ExternalLink class="size-4" /><span class="hidden sm:inline">Camera page</span></a
			>
		{/if}
		<a href="/cameras/{camera.id}/edit" class="btn-ghost"
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

	<!-- The video with what steers it beside it (on phones, under it); everything else folds up
	     below. -->
	<div class="grid items-start gap-6 {caps.has('ptz') ? 'lg:grid-cols-[minmax(0,1fr)_22rem]' : ''}">
		<div class="min-w-0">
			<div
				bind:this={frame}
				data-ptz-keys
				class="group relative overflow-hidden rounded-2xl border border-line bg-black shadow-[0_30px_80px_-40px_rgb(0_0_0/0.9)]"
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
							class="aspect-video w-full"
						/>
					{/key}
				{:else}
					<div class="grid aspect-video place-items-center text-sm text-white/60">
						{camera.enabled ? 'No stream' : 'This camera is disabled'}
					</div>
				{/if}

				<RecordButton {camera} class="absolute top-3 right-3" />
				<div class="absolute top-3 left-3 flex items-center gap-2">
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
					<button
						class="glass-btn"
						onclick={() => (muted = !muted)}
						aria-label={muted ? 'Unmute' : 'Mute'}
					>
						{#if muted}<VolumeX class="size-4" />{:else}<Volume2 class="size-4" />{/if}
					</button>
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
						{#if caps.has('snapshot')}
							<a
								class="glass-btn"
								href={urls.snapshot(camera.id)}
								download="{camera.id}.jpg"
								aria-label="Snapshot"
								title="Snapshot"
							>
								<Camera class="size-4" />
							</a>
						{/if}
						<button class="glass-btn" onclick={fullscreen} aria-label="Fullscreen"
							><Maximize class="size-4" /></button
						>
					</div>
				</div>
			</div>
		</div>
		{#if caps.has('ptz')}
			<!-- The pad stays beside the video, also while scrolling through the panels. -->
			<aside
				class="lg:sticky lg:top-20 lg:row-span-2 lg:max-h-[calc(100dvh-6rem)] lg:overflow-y-auto"
			>
				<Panel title="Pan · Tilt · Zoom" name="ptz" open>
					{#snippet summary()}{presets.length ? `${presets.length} presets` : ''}{/snippet}
					<div class="pt-1"><PtzPad camera={camera.id} /></div>
					<NornPresets {camera} {controls} />
					{#if presets.length}
						<p class="mt-4 mb-2 text-xs font-medium text-muted">The camera's presets</p>
						<div class="flex flex-wrap gap-2">
							{#each presets as preset (preset.id)}
								<button
									class="chip"
									onclick={() =>
										store.attempt(() => api.ptz(id, { action: 'goto', preset: preset.id }))}
								>
									<MapPin class="size-3.5" />{preset.name}
								</button>
							{/each}
						</div>
					{/if}
				</Panel>
			</aside>
		{/if}
		<div class="min-w-0 space-y-4">
			<Panel title="Recent recordings" name="recent" open>
				{#snippet summary()}{recent.length ? `${recent.length} videos` : 'None yet'}{/snippet}
				{#snippet actions()}<a
						href="/recordings?camera={camera.id}"
						class="px-2 text-sm text-accent hover:underline">All</a
					>{/snippet}
				{#if recent.length}
					<div class="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4">
						{#each recent as r (r.id)}
							<RecordingTile
								recording={r}
								cameraName={camera.name}
								onopen={(x) => (open = x)}
								ondelete={remove}
								onpin={pin}
								now={ringNow}
							/>
						{/each}
					</div>
				{:else}
					<p class="py-4 text-center text-sm text-muted">No recordings of this camera yet.</p>
				{/if}
			</Panel>
			<Panel title="Recording & triggers" name="camera-recording">
				{#snippet summary()}{[
						camera.record === 'continuous' ? 'continuous' : '',
						...ownSettings(camera),
						presetsOwn ? `${presetsOwn} ${presetsOwn === 1 ? 'preset' : 'presets'} differ` : ''
					]
						.filter(Boolean)
						.join(' · ') || 'As on Triggers'}{/snippet}
				<!-- Anew for another camera, or when presets come or go. -->
				{#key `${camera.id}:${Object.keys(camera.presets_norn ?? {}).join()}`}
					<CameraRecording {camera} />
				{/key}
			</Panel>
			{#if caps.has('ptz')}
				<Panel title="Patrol & following" name="ptz-auto">
					{#snippet summary()}{[
							camera.patrol?.enabled ? 'Patrols' : '',
							camera.follow !== 'off' ? 'Follows' : '',
							camera.reactions.length ? `${camera.reactions.length} reactions` : ''
						]
							.filter(Boolean)
							.join(' · ') || 'Off'}{/snippet}
					{#key camera.id}<PtzAutomation {camera} />{/key}
				</Panel>
			{/if}

			{#each groups as [group, items] (group)}
				<Panel title={group} name="controls:{group}">
					{#snippet summary()}{items.length} {items.length === 1 ? 'setting' : 'settings'}{/snippet}
					<div class="-mt-1 divide-y divide-line">
						{#each items as control (control.id)}
							<div class="py-2">
								<ControlField {control} onchange={(v) => setControl(control, v)} />
							</div>
						{/each}
					</div>
				</Panel>
			{/each}
			<DeviceCard {camera} />
			<Panel title="Connect" name="connect">
				{#snippet summary()}Home Assistant, RTSP, API{/snippet}
				<CameraConnect {camera} {controls} />
			</Panel>
		</div>
	</div>

	<RecordingDialog bind:recording={open} onchanged={replace} ondeleted={() => loadRecent(id)} />
{/if}
