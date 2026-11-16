<script lang="ts">
	import { api, type Driver, type SettingsData, type SettingsValues } from '#lib/api.js';
	import { store } from '#lib/state.svelte.js';
	import NumberSetting from '#lib/components/NumberSetting.svelte';
	import IntervalSetting from '#lib/components/IntervalSetting.svelte';
	import StorageStages from '#lib/components/StorageStages.svelte';
	import ForecastCard from '#lib/components/ForecastCard.svelte';
	import CloudDownload from '@lucide/svelte/icons/cloud-download';
	import Database from '@lucide/svelte/icons/database';
	import Cpu from '@lucide/svelte/icons/cpu';
	import ResourceUsage from '#lib/components/ResourceUsage.svelte';
	import Server from '@lucide/svelte/icons/server';
	import Radio from '@lucide/svelte/icons/radio';
	import HardDrive from '@lucide/svelte/icons/hard-drive';
	import FileCode from '@lucide/svelte/icons/file-code';
	import Puzzle from '@lucide/svelte/icons/puzzle';
	import Cctv from '@lucide/svelte/icons/cctv';

	let drivers = $state<Driver[]>([]);
	$effect(() => {
		api.drivers().then((d) => (drivers = d));
	});

	const info = $derived(store.info);

	// The settings form: a copy of the saved values, saved as a whole.
	let saved = $state<SettingsValues | null>(null);
	let defaults = $state<SettingsValues | null>(null);
	let form = $state<SettingsValues | null>(null);
	let saving = $state(false);
	const dirty = $derived(!!form && JSON.stringify(form) !== JSON.stringify(saved));

	function take(data: SettingsData) {
		saved = data.values;
		defaults = data.defaults;
		form = structuredClone(data.values);
	}

	function reset() {
		if (saved) form = structuredClone($state.snapshot(saved));
	}

	async function save() {
		if (!form) return;
		saving = true;
		const data = await store.attempt(() => api.saveSettings($state.snapshot(form!)), 'Saved');
		saving = false;
		if (data) take(data);
	}

	$effect(() => {
		api.settings().then(take);
		// Someone else saved, or config.yaml was edited by hand: show it, unless we are editing.
		return store.on((e) => {
			if ((e.type === 'settings.changed' || e.type === 'cameras.changed') && !dirty) {
				api.settings().then(take);
			}
		});
	});
	const origin = $derived(typeof location === 'undefined' ? '' : location.origin);
</script>

<svelte:head><title>Settings · Norn</title></svelte:head>

<div class="mx-auto max-w-3xl space-y-6">
	<div>
		<h1 class="text-2xl font-semibold tracking-tight">Settings</h1>
		<p class="mt-1 text-sm text-muted">
			Norn keeps its settings in <code class="font-mono text-text">config.yaml</code>. Edit it by
			hand or here; both keep the other's changes.
		</p>
	</div>

	<section class="overflow-hidden card">
		<div class="flex items-center gap-2 p-5 pb-3 text-muted">
			<Cctv class="size-4" /><span class="eyebrow">Cameras</span>
		</div>
		<div class="overflow-x-auto">
			<table class="w-full text-sm">
				<thead>
					<tr class="border-b border-line text-left text-xs text-muted">
						<th class="px-5 py-2 font-medium">Camera</th>
						<th class="px-3 py-2 font-medium">Model</th>
						<th class="px-3 py-2 font-medium">Firmware</th>
						<th class="px-5 py-2 font-medium">Status</th>
					</tr>
				</thead>
				<tbody class="divide-y divide-line">
					{#each store.cameras as c (c.id)}
						<tr>
							<td class="px-5 py-3"
								><a class="font-medium hover:text-accent" href="/cameras/{c.id}">{c.name}</a></td
							>
							<td class="px-3 py-3 text-muted">
								{[c.device?.manufacturer, c.device?.model].filter(Boolean).join(' ') || c.driver}
							</td>
							<td class="px-3 py-3 font-mono text-xs text-muted">{c.device?.firmware ?? '–'}</td>
							<td class="px-5 py-3">
								{#if !c.enabled}
									<span class="text-muted">Disabled</span>
								{:else if c.device && !c.device.online}
									<span class="text-danger">Offline</span>
								{:else if c.firmware?.status === 'update'}
									<span class="text-warning">Update available</span>
								{:else if c.firmware?.status === 'end-of-life'}
									<span class="text-muted">No more updates</span>
								{:else if c.device}
									<span class="text-success">OK</span>
								{:else}
									<span class="text-muted">…</span>
								{/if}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	</section>

	<section class="grid gap-4 sm:grid-cols-2">
		<div class="card p-5">
			<div class="mb-3 flex items-center gap-2 text-muted">
				<Server class="size-4" /><span class="eyebrow">Norn</span>
			</div>
			<div class="text-2xl font-semibold tabular-nums">{info?.version ?? '–'}</div>
			<p class="mt-1 text-xs text-muted">
				{store.connected ? 'Connected to the server' : 'Not connected'}
			</p>
		</div>
		<div class="card p-5">
			<div class="mb-3 flex items-center gap-2 text-muted">
				<Radio class="size-4" /><span class="eyebrow">go2rtc</span>
			</div>
			<div class="flex items-center gap-2 text-2xl font-semibold">
				<span class="size-2.5 rounded-full {info?.go2rtc.running ? 'bg-success' : 'bg-danger'}"
				></span>
				{info?.go2rtc.running ? 'Running' : 'Not running'}
			</div>
			<p class="mt-1 text-xs text-muted">
				{info?.go2rtc.version ? `Version ${info.go2rtc.version} · ` : ''}Relays the video without
				re-encoding it.
			</p>
		</div>
	</section>

	{#if form && defaults}
		<form
			class="divide-y divide-line card"
			onsubmit={(e) => {
				e.preventDefault();
				save();
			}}
		>
			<div class="flex items-center gap-2 p-5 text-muted">
				<HardDrive class="size-4" /><span class="eyebrow">Recording</span>
				{#if info && !info.recording_available}
					<span class="ml-auto text-xs text-danger">Off: needs go2rtc and FFmpeg</span>
				{/if}
			</div>
			<NumberSetting
				label="Keep automatic recordings"
				hint="Continuous video, triggered clips and pictures. Clips you record by hand stay. 0 keeps all."
				bind:value={form.recording.retention_days}
				fallback={defaults.recording.retention_days}
				unit="days"
			/>
			<NumberSetting
				label="Continuous file length"
				hint="A continuous recording starts a new file this often."
				bind:value={form.recording.segment_minutes}
				fallback={defaults.recording.segment_minutes}
				min={1}
				max={60}
				unit="min"
			/>
			<NumberSetting
				label="Clip length"
				hint="How long a clip runs when a button, webhook or motion starts it."
				bind:value={form.recording.clip_seconds}
				fallback={defaults.recording.clip_seconds}
				min={5}
				max={3600}
				unit="sec"
			/>
			<NumberSetting
				label="Record before the trigger"
				hint="Each camera's last seconds wait in RAM, so a clip starts before its trigger. MJPEG cameras only when set on the camera. 0: off."
				bind:value={form.recording.prebuffer_seconds}
				fallback={defaults.recording.prebuffer_seconds}
				max={300}
				unit="sec"
			/>
			<IntervalSetting
				label="Pictures"
				hint="A picture of every camera on a timer. Circles and cameras can set their own."
				bind:value={form.recording.picture_seconds}
			/>
			<div class="flex items-center gap-2 p-5 pb-1 text-muted">
				<CloudDownload class="size-4" /><span class="eyebrow">Firmware</span>
			</div>
			<NumberSetting
				label="Check for new firmware"
				hint="Asks the vendors, where the driver can; cameras with automatic updates install then. 0: never."
				bind:value={form.firmware.check_hours}
				fallback={defaults.firmware.check_hours}
				max={2160}
				unit="hours"
			/>
			<div class="flex items-center justify-end gap-2 px-5 py-3.5">
				{#if dirty}
					<button type="button" class="btn-ghost" onclick={reset}>Discard</button>
				{/if}
				<button class="btn-primary" disabled={!dirty || saving}>
					{saving ? 'Saving…' : 'Save'}
				</button>
			</div>
		</form>
	{/if}

	<section class="card p-5">
		<div class="mb-4 flex items-center gap-2 text-muted">
			<Cpu class="size-4" /><span class="eyebrow">Resources</span>
		</div>
		<ResourceUsage />
	</section>

	<section class="card p-5">
		<div class="mb-4 flex items-center gap-2 text-muted">
			<Database class="size-4" /><span class="eyebrow">Storage</span>
		</div>
		<StorageStages />
		<h3 class="mt-6 mb-3 text-sm font-semibold">Forecast</h3>
		<ForecastCard />
		<p class="mt-3 text-xs text-muted">
			Set the folders with <code class="font-mono">NORN_BUFFER</code>,
			<code class="font-mono">NORN_TEMP</code> and <code class="font-mono">NORN_RECORDINGS</code>.
		</p>
	</section>

	<section class="card p-5">
		<div class="mb-3 flex items-center gap-2 text-muted">
			<FileCode class="size-4" /><span class="eyebrow">Webhook</span>
		</div>
		<p class="text-sm text-muted">
			Start a clip from anything that can send an HTTP request, like Home Assistant or a doorbell:
		</p>
		<pre
			class="mt-3 overflow-x-auto rounded-xl bg-surface-2 p-4 font-mono text-xs leading-relaxed">curl -X POST {origin}/api/cameras/<span
				class="text-accent">CAMERA</span
			>/record \
  -H 'Content-Type: application/json' \
  -d '&#123;"trigger": "doorbell", "seconds": 30&#125;'</pre>
		<p class="mt-3 text-xs text-muted">
			All endpoints: <a class="text-accent hover:underline" href="/api/docs">API docs</a> · Config
			file:
			<code class="font-mono">{info?.config_path ?? ''}</code>
		</p>
	</section>

	<section class="card p-5">
		<div class="mb-4 flex items-center gap-2 text-muted">
			<Puzzle class="size-4" /><span class="eyebrow">Camera drivers</span>
		</div>
		<div class="grid gap-3 sm:grid-cols-2">
			{#each drivers as d (d.name)}
				<div class="rounded-xl border border-line bg-surface-2/60 p-4">
					<div class="flex items-center justify-between">
						<span class="text-sm font-semibold">{d.label}</span>
						<code class="font-mono text-xs text-muted">{d.name}</code>
					</div>
					<p class="mt-1 text-xs text-muted">{d.description}</p>
				</div>
			{/each}
		</div>
	</section>
</div>
