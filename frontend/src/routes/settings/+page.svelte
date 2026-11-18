<script lang="ts">
	// Norn's settings, in tabs: recording, firmware, MQTT. One form for all of them, with Save and
	// Discard at the top. What records is on Triggers; Diagnostics and Help are pages too.
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { store } from '#lib/state.svelte.js';
	import { install } from '#lib/install.svelte.js';
	import { SettingsForm } from '#lib/settings-form.svelte.js';
	import SaveBar from '#lib/components/SaveBar.svelte';
	import SettingsSection from '#lib/components/SettingsSection.svelte';
	import NumberSetting from '#lib/components/NumberSetting.svelte';
	import TextSetting from '#lib/components/TextSetting.svelte';
	import ChoiceSetting from '#lib/components/ChoiceSetting.svelte';
	import HouseWifi from '@lucide/svelte/icons/house-wifi';
	import HardDrive from '@lucide/svelte/icons/hard-drive';
	import Archive from '@lucide/svelte/icons/archive';
	import CloudDownload from '@lucide/svelte/icons/cloud-download';
	import Activity from '@lucide/svelte/icons/activity';
	import CircleHelp from '@lucide/svelte/icons/circle-help';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import Download from '@lucide/svelte/icons/download';

	const MORE = [
		{
			href: '/diagnostics',
			label: 'Diagnostics',
			hint: 'Version, CPU and memory, storage, the log',
			icon: Activity
		},
		{
			href: '/help',
			label: 'Help',
			hint: 'Connecting other things, where to find more',
			icon: CircleHelp
		}
	];

	const TABS = [
		['recording', 'Recording'],
		['firmware', 'Firmware'],
		['mqtt', 'MQTT']
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
	const mqtt = $derived(info?.mqtt);
	const ON_OFF: [boolean, string][] = [
		[true, 'On'],
		[false, 'Off']
	];
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
	<!-- Phones have no room for these in the bottom bar: they open from here, as a menu. -->
	<nav class="-mt-1 divide-y divide-line overflow-hidden card md:hidden" aria-label="More">
		{#each MORE as item (item.href)}
			<a href={item.href} class="flex items-center gap-3 px-4 py-3 active:bg-surface-3">
				<item.icon class="size-5 shrink-0 text-muted" />
				<span class="min-w-0 flex-1">
					<span class="block text-sm font-medium">{item.label}</span>
					<span class="block truncate text-xs text-muted">{item.hint}</span>
				</span>
				<ChevronRight class="size-4 shrink-0 text-muted" />
			</a>
		{/each}
		{#if !install.installed}
			{#if install.offered}
				<button
					class="flex w-full items-center gap-3 px-4 py-3 text-left active:bg-surface-3"
					onclick={() => install.install()}
				>
					<Download class="size-5 shrink-0 text-accent" />
					<span class="min-w-0 flex-1">
						<span class="block text-sm font-medium">Install the app</span>
						<span class="block truncate text-xs text-muted">Its own icon, full screen</span>
					</span>
				</button>
			{:else}
				<a href="/help#install" class="flex items-center gap-3 px-4 py-3 active:bg-surface-3">
					<Download class="size-5 shrink-0 text-muted" />
					<span class="min-w-0 flex-1">
						<span class="block text-sm font-medium">Install the app</span>
						<span class="block truncate text-xs text-muted">How to add Norn to the home screen</span
						>
					</span>
					<ChevronRight class="size-4 shrink-0 text-muted" />
				</a>
			{/if}
		{/if}
	</nav>

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
		{:else if tab === 'mqtt'}
			<SettingsSection
				title="MQTT"
				description="For Home Assistant and other home automation: Norn publishes each camera's detections, recording, controls and presets to an MQTT broker and takes commands from it. With discovery, the cameras appear in Home Assistant by themselves."
				icon={HouseWifi}
			>
				{#snippet aside()}
					{#if mqtt?.enabled}
						<span class="text-xs {mqtt.connected ? 'text-success' : 'text-danger'}"
							>{mqtt.connected ? 'Connected' : (mqtt.error ?? 'Connecting')}</span
						>
					{/if}
				{/snippet}
				<ChoiceSetting label="MQTT" bind:value={form.mqtt.enabled} choices={ON_OFF} />
				<TextSetting
					label="Broker"
					hint="Its host name or address, like homeassistant.local."
					bind:value={form.mqtt.host}
					fallback={defaults.mqtt.host}
					placeholder="homeassistant.local"
				/>
				<NumberSetting
					label="Port"
					hint="0: 1883, or 8883 with TLS."
					bind:value={form.mqtt.port}
					fallback={defaults.mqtt.port}
					max={65535}
				/>
				<ChoiceSetting label="TLS" bind:value={form.mqtt.tls} choices={ON_OFF} />
				<TextSetting
					label="User"
					bind:value={form.mqtt.username}
					fallback={defaults.mqtt.username}
				/>
				<TextSetting
					label="Password"
					type="password"
					hint={settings.secrets?.mqtt.includes('password') ? 'Set. Left empty, it stays.' : ''}
					bind:value={form.mqtt.password}
					placeholder={settings.secrets?.mqtt.includes('password') ? 'Unchanged' : ''}
				/>
				<TextSetting
					label="Topic prefix"
					hint="Norn's topics start with it. Letters, digits, _ and -."
					bind:value={form.mqtt.prefix}
					fallback={defaults.mqtt.prefix}
				/>
				<ChoiceSetting
					label="Home Assistant discovery"
					hint="The cameras appear in Home Assistant with their entities."
					bind:value={form.mqtt.discovery}
					choices={ON_OFF}
				/>
				{#if form.mqtt.discovery}
					<TextSetting
						label="Discovery prefix"
						hint="Home Assistant's; the same there."
						bind:value={form.mqtt.discovery_prefix}
						fallback={defaults.mqtt.discovery_prefix}
					/>
				{/if}
				<NumberSetting
					label="Stills"
					hint="Send each camera's picture this often, for a camera entity (at least 5 s). 0: none."
					bind:value={form.mqtt.stills_seconds}
					fallback={defaults.mqtt.stills_seconds}
					max={86400}
					unit="s"
				/>
			</SettingsSection>
			<p class="px-1 text-xs text-muted">
				The defaults come from the <code class="font-mono">NORN_MQTT</code> environment variables; config.yaml
				keeps what differs from them. Norn connects again when you save.
			</p>
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
