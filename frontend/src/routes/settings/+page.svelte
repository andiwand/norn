<script lang="ts">
	// Norn's settings, in tabs: recording, firmware. One form for all of them, with Save and
	// Discard at the top. What records is on Triggers; Diagnostics and Help are pages too.
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { store } from '#lib/state.svelte.js';
	import { install } from '#lib/install.svelte.js';
	import { SettingsForm } from '#lib/settings-form.svelte.js';
	import SaveBar from '#lib/components/SaveBar.svelte';
	import SettingsSection from '#lib/components/SettingsSection.svelte';
	import NumberSetting from '#lib/components/NumberSetting.svelte';
	import HardDrive from '@lucide/svelte/icons/hard-drive';
	import Archive from '@lucide/svelte/icons/archive';
	import CloudDownload from '@lucide/svelte/icons/cloud-download';

	const TABS = [
		['recording', 'Recording'],
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
</script>

<svelte:head><title>Settings · Norn</title></svelte:head>

<div class="mx-auto max-w-3xl space-y-5">
	<SaveBar
		title="Settings"
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
	<p class="page-intro -mt-4">
		Kept in <code class="font-mono text-text">config.yaml</code>: edit it by hand or here; both keep
		the other's changes.
	</p>
	<!-- Phones have no room for these in the bottom bar. -->
	<div class="-mt-2 flex gap-1.5 md:hidden">
		<a class="chip" href="/diagnostics">Diagnostics</a>
		<a class="chip" href="/help">Help</a>
		{#if !install.installed}
			{#if install.offered}
				<button class="chip chip-active" onclick={() => install.install()}>Install app</button>
			{:else}
				<a class="chip" href="/help#install">Install app</a>
			{/if}
		{/if}
	</div>

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
				title="Continuous recording"
				description="Cameras set to record continuously keep everything, in files of a few minutes. What starts clips and pictures is on Triggers."
				icon={HardDrive}
			>
				<NumberSetting
					label="File length"
					hint="A continuous recording starts a new file this often."
					bind:value={form.recording.segment_minutes}
					fallback={defaults.recording.segment_minutes}
					min={1}
					max={60}
					unit="min"
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
