<script lang="ts">
	// Norn's settings, in tabs: recording, detection, firmware. One form for all of them, with
	// Save and Discard at the top. Diagnostics and Help are pages of their own.
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import type { Window } from '#lib/api.js';
	import { store } from '#lib/state.svelte.js';
	import { SettingsForm } from '#lib/settings-form.svelte.js';
	import SaveBar from '#lib/components/SaveBar.svelte';
	import SettingsSection from '#lib/components/SettingsSection.svelte';
	import NumberSetting from '#lib/components/NumberSetting.svelte';
	import IntervalSetting from '#lib/components/IntervalSetting.svelte';
	import TriggerSetting from '#lib/components/TriggerSetting.svelte';
	import ScheduleSetting from '#lib/components/ScheduleSetting.svelte';
	import ChoiceSetting from '#lib/components/ChoiceSetting.svelte';
	import HardDrive from '@lucide/svelte/icons/hard-drive';
	import Archive from '@lucide/svelte/icons/archive';
	import Zap from '@lucide/svelte/icons/zap';
	import ScanEye from '@lucide/svelte/icons/scan-eye';
	import CloudDownload from '@lucide/svelte/icons/cloud-download';

	const TABS = [
		['recording', 'Recording'],
		['detection', 'Detection'],
		['firmware', 'Firmware']
	] as const;
	type Tab = (typeof TABS)[number][0];
	const tab = $derived<Tab>(
		TABS.find(([id]) => id === page.url.searchParams.get('tab'))?.[0] ?? 'recording'
	);
	function show(next: Tab) {
		goto(next === 'recording' ? '/settings' : `/settings?tab=${next}`, {
			replace: true,
			reset: false
		});
	}

	const settings = new SettingsForm();
	$effect(() => settings.watch());
	const form = $derived(settings.form);
	const defaults = $derived(settings.defaults);

	const info = $derived(store.info);
	const clockDiffers = $derived(
		!!info?.time && info.time.offset_minutes !== -new Date().getTimezoneOffset()
	);
	function offset(minutes: number): string {
		const sign = minutes < 0 ? '−' : '+';
		const m = Math.abs(minutes);
		return `${sign}${Math.floor(m / 60)}${m % 60 ? `:${String(m % 60).padStart(2, '0')}` : ''}`;
	}
</script>

<svelte:head><title>Settings · Norn</title></svelte:head>

<div class="mx-auto max-w-3xl space-y-5">
	<div>
		<h1 class="text-2xl font-semibold tracking-tight">Settings</h1>
		<p class="mt-1 text-sm text-muted">
			Kept in <code class="font-mono text-text">config.yaml</code>: edit it by hand or here; both
			keep the other's changes.
		</p>
	</div>

	<!-- Phones have no room for these in the bottom bar. -->
	<div class="-mt-2 flex gap-1.5 md:hidden">
		<a class="chip" href="/diagnostics">Diagnostics</a>
		<a class="chip" href="/help">Help</a>
	</div>

	<SaveBar
		dirty={settings.dirty}
		saving={settings.saving}
		onsave={() => settings.save()}
		ondiscard={() => settings.reset()}
	>
		<div class="flex rounded-xl bg-surface-3 p-1" role="tablist" aria-label="Settings">
			{#each TABS as [id, label] (id)}
				<button
					role="tab"
					aria-selected={tab === id}
					class="rounded-lg px-3 py-1.5 text-sm font-medium transition {tab === id
						? 'bg-surface text-text shadow'
						: 'text-muted hover:text-text'}"
					onclick={() => show(id)}>{label}</button
				>
			{/each}
		</div>
	</SaveBar>

	{#if form && defaults}
		{#if tab === 'recording'}
			<SettingsSection
				title="Keeping recordings"
				description="Norn deletes what it recorded by itself when it gets old or the disk gets full, the oldest first. Clips you record by hand, and pinned recordings, stay."
				icon={Archive}
			>
				{#snippet aside()}
					{#if info && !info.recording_available}
						<span class="text-xs text-danger">Recording is off: needs go2rtc and FFmpeg</span>
					{/if}
				{/snippet}
				<NumberSetting
					label="Keep for"
					hint="0 keeps them until the limits below."
					bind:value={form.recording.retention_days}
					fallback={defaults.recording.retention_days}
					unit="days"
				/>
				<NumberSetting
					label="Keep at most"
					hint="The most all recordings may take. 0: no limit."
					bind:value={form.recording.max_gb}
					fallback={defaults.recording.max_gb}
					step={1}
					unit="GB"
				/>
				<NumberSetting
					label="Keep free on the disk"
					hint="0: no limit."
					bind:value={form.recording.min_free_gb}
					fallback={defaults.recording.min_free_gb}
					step={1}
					unit="GB"
				/>
			</SettingsSection>

			<SettingsSection
				title="How Norn records"
				description="The length of files and clips, the seconds a clip includes from before its trigger, and pictures on a timer."
				icon={HardDrive}
			>
				<NumberSetting
					label="Clip length"
					hint="After a button, a webhook, or the end of a detection."
					bind:value={form.recording.clip_seconds}
					fallback={defaults.recording.clip_seconds}
					min={5}
					max={3600}
					unit="sec"
				/>
				<NumberSetting
					label="Record before the trigger"
					hint="Each camera's last seconds wait in RAM. MJPEG cameras only when set on the camera. 0: off."
					bind:value={form.recording.prebuffer_seconds}
					fallback={defaults.recording.prebuffer_seconds}
					max={300}
					unit="sec"
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
				<IntervalSetting
					label="Pictures"
					hint="A picture of every camera on a timer. Circles and cameras can set their own."
					bind:value={form.recording.picture_seconds}
				/>
			</SettingsSection>
		{:else if tab === 'detection'}
			<SettingsSection
				title="What records"
				description="Detections that start a clip, from the cameras themselves or from Norn. A clip runs while the detection lasts, plus the clip length. Circles and cameras can have their own."
				icon={Zap}
			>
				<TriggerSetting label="Record on" bind:value={form.recording.triggers} />
				{#if clockDiffers}
					<p class="mx-5 my-3 rounded-xl bg-warning/10 px-3 py-2 text-xs text-warning">
						Norn's clock runs in {info?.time.zone} (UTC{offset(info?.time.offset_minutes ?? 0)}),
						this browser in UTC{offset(-new Date().getTimezoneOffset())}. Schedules follow Norn's
						clock: set <code class="font-mono">TZ</code> to your time zone.
					</p>
				{/if}
				<ScheduleSetting
					label="When"
					hint="Only in these times, e.g. at night. Away mode records at any time."
					bind:value={form.recording.schedule as Window[] | null}
				/>
			</SettingsSection>

			<SettingsSection
				title="Detection by Norn"
				description="Besides what the cameras detect themselves, Norn can look at a still of each camera every few seconds. What it finds becomes the same triggers."
				icon={ScanEye}
			>
				<ChoiceSetting
					label="Motion"
					hint="Compares the stills. Costs almost nothing."
					bind:value={form.detection.motion}
					choices={[
						[false, 'Off'],
						[true, 'On']
					]}
				/>
				<ChoiceSetting
					label="People, vehicles, animals"
					hint={info?.detection.objects_unavailable
						? `Not available: ${info.detection.objects_unavailable}.`
						: 'A small AI model on the CPU, about 20 ms per still.'}
					bind:value={form.detection.objects}
					disabled={!!info?.detection.objects_unavailable}
					choices={[
						[false, 'Off'],
						[true, 'On']
					]}
				/>
				<NumberSetting
					label="Look every"
					hint="How often Norn checks a still of each camera."
					bind:value={form.detection.every_seconds}
					fallback={defaults.detection.every_seconds}
					min={0.5}
					max={60}
					step={0.5}
					unit="sec"
				/>
				<ChoiceSetting
					label="Stills"
					hint="Keyframes cost next to nothing but come every few seconds; every frame is exact and uses more CPU."
					bind:value={form.detection.stills}
					choices={[
						['auto', 'Auto'],
						['keyframe', 'Keyframes'],
						['live', 'Every frame']
					]}
				/>
				<NumberSetting
					label="Motion sensitivity"
					hint="Higher reacts to smaller changes."
					bind:value={form.detection.sensitivity}
					fallback={defaults.detection.sensitivity}
					max={100}
					unit="%"
				/>
				<NumberSetting
					label="Certainty"
					hint="How sure the AI must be about an object (0.1 to 0.95)."
					bind:value={form.detection.min_score}
					fallback={defaults.detection.min_score}
					min={0.1}
					max={0.95}
					step={0.05}
				/>
				<ChoiceSetting
					label="Model"
					hint="Tiny finds more, at about four times the CPU."
					bind:value={form.detection.model}
					choices={[
						['nano', 'Nano'],
						['tiny', 'Tiny']
					]}
				/>
			</SettingsSection>
		{:else}
			<SettingsSection
				title="Firmware updates"
				description="Norn asks the vendors for new firmware where the driver can. Cameras with automatic updates (in their Device panel) install it then."
				icon={CloudDownload}
			>
				<NumberSetting
					label="Check every"
					hint="0: never."
					bind:value={form.firmware.check_hours}
					fallback={defaults.firmware.check_hours}
					max={2160}
					unit="hours"
				/>
			</SettingsSection>
		{/if}
	{:else}
		<div class="h-64 animate-pulse rounded-2xl bg-surface-2"></div>
	{/if}
</div>
