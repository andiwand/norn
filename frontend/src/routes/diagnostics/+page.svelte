<script lang="ts">
	// How Norn is doing: its version, go2rtc, what it costs, what it stores, and its log.
	import { store } from '#lib/state.svelte.js';
	import SettingsSection from '#lib/components/SettingsSection.svelte';
	import ResourceUsage from '#lib/components/ResourceUsage.svelte';
	import StorageStages from '#lib/components/StorageStages.svelte';
	import ForecastCard from '#lib/components/ForecastCard.svelte';
	import LogView from '#lib/components/LogView.svelte';
	import Server from '@lucide/svelte/icons/server';
	import Radio from '@lucide/svelte/icons/radio';
	import HouseWifi from '@lucide/svelte/icons/house-wifi';
	import Cpu from '@lucide/svelte/icons/cpu';
	import Database from '@lucide/svelte/icons/database';
	import ScrollText from '@lucide/svelte/icons/scroll-text';

	const info = $derived(store.info);
	const mqtt = $derived(info?.mqtt);

	const when = (seconds: number) =>
		new Date(seconds * 1000).toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' });
</script>

<svelte:head><title>Diagnostics · Norn</title></svelte:head>

<div class="mx-auto max-w-3xl space-y-5">
	<div>
		<h1 class="page-title">Diagnostics</h1>
		<p class="page-intro">What Norn runs, what it costs, and what it stores.</p>
	</div>

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
		<div class="card p-5 sm:col-span-2">
			<div class="mb-3 flex items-center gap-2 text-muted">
				<HouseWifi class="size-4" /><span class="eyebrow">MQTT</span>
			</div>
			<div class="flex items-center gap-2 text-2xl font-semibold">
				<span
					class="size-2.5 rounded-full {!mqtt?.enabled
						? 'bg-muted'
						: mqtt.connected
							? 'bg-success'
							: 'bg-danger'}"
				></span>
				{!mqtt?.enabled ? 'Off' : mqtt.connected ? 'Connected' : 'Not connected'}
			</div>
			<p class="mt-1 text-xs break-words text-muted">
				{#if !mqtt?.enabled}
					For Home Assistant: set NORN_MQTT to a broker, like
					<code class="font-mono">mqtt://user:password@homeassistant.local</code>.
				{:else if mqtt.connected}
					{mqtt.broker}{mqtt.since ? ` · since ${when(mqtt.since)}` : ''} · topics under
					<code class="font-mono">{mqtt.prefix}/</code>{mqtt.discovery
						? ', in Home Assistant by discovery'
						: ''}.
				{:else}
					{mqtt.broker}: {mqtt.error ?? 'connecting'}. Norn tries again by itself.
				{/if}
			</p>
			{#if mqtt?.last_error}
				<p class="mt-2 text-xs break-words text-danger">
					Last failed command ({when(Date.parse(mqtt.last_error.time) / 1000)}):
					<code class="font-mono">{mqtt.last_error.command}</code>: {mqtt.last_error.error}
				</p>
			{/if}
		</div>
	</section>

	<SettingsSection
		title="Resources"
		description="CPU and memory of Norn and the programs it runs."
		icon={Cpu}
	>
		<div class="p-5"><ResourceUsage /></div>
	</SettingsSection>

	<SettingsSection
		title="Storage"
		description="The three stages of a recording: the last seconds in RAM, what is being recorded, and the finished recordings. Set the folders with NORN_BUFFER, NORN_TEMP and NORN_RECORDINGS."
		icon={Database}
	>
		<div class="p-5"><StorageStages /></div>
		<div class="p-5">
			<h3 class="mb-3 text-sm font-semibold">Forecast</h3>
			<ForecastCard />
		</div>
	</SettingsSection>

	<SettingsSection
		title="Log"
		description="The latest messages; also in the log file."
		icon={ScrollText}
	>
		<div class="p-5"><LogView /></div>
	</SettingsSection>
</div>
