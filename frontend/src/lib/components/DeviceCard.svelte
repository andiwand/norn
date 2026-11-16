<script lang="ts">
	// What the camera says about itself, its firmware, and the firmware update.
	import { api, cameraBody, type Camera } from '../api';
	import { store } from '../state.svelte';
	import RefreshCw from '@lucide/svelte/icons/refresh-cw';
	import Upload from '@lucide/svelte/icons/upload';
	import ExternalLink from '@lucide/svelte/icons/external-link';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import LoaderCircle from '@lucide/svelte/icons/loader-circle';
	import Panel from './Panel.svelte';

	let { camera }: { camera: Camera } = $props();

	let refreshing = $state(false);
	let confirming = $state<File | null>(null);
	let fileInput = $state<HTMLInputElement>();

	const device = $derived(camera.device);
	const firmware = $derived(camera.firmware);
	const caps = $derived(new Set(camera.capabilities));
	const canUpload = $derived(caps.has('firmware-upload'));
	const canOnline = $derived(caps.has('firmware-online'));
	const running = $derived(camera.update?.state === 'running');

	const status = {
		current: { label: 'Up to date', class: 'bg-success/15 text-success' },
		update: { label: 'Update available', class: 'bg-accent/15 text-accent' },
		'end-of-life': { label: 'No more updates', class: 'bg-surface-3 text-muted' },
		unknown: { label: 'Unknown', class: 'bg-surface-3 text-muted' }
	};

	async function refresh() {
		refreshing = true;
		await store.attempt(() => api.refreshDevice(camera.id));
		await store.refresh();
		refreshing = false;
	}

	async function install(file?: File) {
		confirming = null;
		store.toast('Installing firmware. The camera restarts and is offline for a few minutes.');
		const ok = await store.attempt(() => api.updateFirmware(camera.id, file), 'Firmware installed');
		if (ok) store.refresh();
	}

	function setAutoUpdate(value: boolean) {
		store.attempt(() => api.updateCamera(camera.id, cameraBody(camera, { auto_update: value })));
	}

	const rows = $derived(
		[
			['Manufacturer', device?.manufacturer],
			['Model', device?.model],
			['Name on camera', device?.name],
			['Hardware', device?.hardware],
			['Serial', device?.serial],
			['MAC', device?.mac],
			...Object.entries(device?.details ?? {})
		].filter(([, v]) => v) as [string, string][]
	);
</script>

<Panel title="Device">
	{#snippet summary()}
		{#if device && !device.online}
			<span class="text-danger">Offline</span>
		{:else if running}
			Installing firmware…
		{:else if firmware}
			<span class={firmware.status === 'update' ? 'text-accent' : ''}
				>{status[firmware.status].label}</span
			>
		{:else if device}
			{device.model ?? 'Online'}
		{/if}
	{/snippet}
	{#snippet actions()}
		<button
			class="icon-btn size-8"
			onclick={refresh}
			aria-label="Read the camera again"
			title="Read again"
		>
			<RefreshCw class="size-4 {refreshing ? 'animate-spin' : ''}" />
		</button>
	{/snippet}

	{#if !device}
		<p class="text-sm text-muted">Reading the camera…</p>
	{:else if !device.online}
		<div class="flex items-start gap-2 rounded-xl bg-danger/10 px-3 py-2.5 text-sm text-danger">
			<TriangleAlert class="mt-0.5 size-4 shrink-0" />
			<span>Offline: {device.error}</span>
		</div>
	{:else}
		<dl class="space-y-1.5 text-sm">
			{#each rows as [label, value] (label)}
				<div class="flex justify-between gap-4">
					<dt class="text-muted">{label}</dt>
					<dd class="min-w-0 truncate text-right font-medium" title={value}>{value}</dd>
				</div>
			{/each}
		</dl>
	{/if}

	{#if firmware}
		<div class="mt-4 border-t border-line pt-4">
			<div class="flex items-center justify-between gap-2">
				<span class="text-sm font-medium">Firmware</span>
				<span
					class="rounded-full px-2.5 py-0.5 text-xs font-medium {status[firmware.status].class}"
				>
					{status[firmware.status].label}
				</span>
			</div>
			<dl class="mt-2 space-y-1.5 text-sm">
				<div class="flex justify-between gap-4">
					<dt class="text-muted">Installed</dt>
					<dd class="truncate font-mono text-xs">{firmware.current ?? '?'}</dd>
				</div>
				{#if firmware.latest}
					<div class="flex justify-between gap-4">
						<dt class="text-muted">Latest</dt>
						<dd class="truncate text-right font-mono text-xs">
							{firmware.latest}{#if firmware.released}<span class="block font-sans text-muted"
									>released {firmware.released}</span
								>{/if}
						</dd>
					</div>
				{/if}
			</dl>
			{#each firmware.notes as note (note)}
				<p class="mt-2 text-xs text-muted">{note}</p>
			{/each}
			{#if firmware.url}
				<a
					href={firmware.url}
					target="_blank"
					rel="noreferrer"
					class="mt-2 inline-flex items-center gap-1 text-xs text-accent hover:underline"
				>
					Vendor downloads <ExternalLink class="size-3" />
				</a>
			{/if}

			{#if camera.update?.state === 'failed'}
				<p class="mt-3 rounded-xl bg-danger/10 px-3 py-2 text-xs text-danger">
					Last update failed: {camera.update.error}
				</p>
			{/if}

			<div class="mt-3 space-y-2">
				{#if running}
					<div class="flex items-center gap-2 text-sm text-muted">
						<LoaderCircle class="size-4 animate-spin" />Installing firmware…
					</div>
				{:else if confirming}
					<div class="rounded-xl border border-warning/40 bg-warning/10 p-3 text-xs">
						<p>
							Install <b>{confirming.name}</b> on {camera.name}? The camera restarts and is offline
							for a few minutes. Don't cut its power. A wrong file is refused by the camera.
						</p>
						<div class="mt-2 flex justify-end gap-2">
							<button class="btn-ghost h-8 px-3 text-xs" onclick={() => (confirming = null)}
								>Cancel</button
							>
							<button
								class="btn h-8 bg-warning px-3 text-xs text-black"
								onclick={() => install(confirming ?? undefined)}>Install</button
							>
						</div>
					</div>
				{:else}
					{#if canOnline && firmware.status === 'update'}
						<button class="btn-primary h-9 w-full" onclick={() => install()}>Update now</button>
					{/if}
					{#if canUpload}
						<input
							bind:this={fileInput}
							type="file"
							class="hidden"
							onchange={(e) => (confirming = e.currentTarget.files?.[0] ?? null)}
						/>
						<button class="btn-ghost h-9 w-full" onclick={() => fileInput?.click()}>
							<Upload class="size-4" />Install firmware file…
						</button>
					{/if}
				{/if}

				<label
					class="flex items-start justify-between gap-3 pt-1 {canOnline
						? 'cursor-pointer'
						: 'opacity-60'}"
				>
					<span>
						<span class="block text-sm font-medium">Update automatically</span>
						<span class="block text-xs text-muted">
							{#if canOnline}
								Norn checks daily and installs new firmware by itself.
							{:else}
								Needs a camera that can fetch firmware online; this one can't.
								{#if camera.auto_update}It's on, and takes effect once it can.{/if}
							{/if}
						</span>
					</span>
					<input
						type="checkbox"
						class="mt-1 size-4 accent-[var(--accent)]"
						checked={camera.auto_update}
						onchange={(e) => setAutoUpdate(e.currentTarget.checked)}
					/>
				</label>
			</div>
		</div>
	{/if}

	{#if device?.notes.length}
		<div class="mt-4 space-y-1.5 border-t border-line pt-4">
			{#each device.notes as note (note)}
				<p class="flex gap-2 text-xs text-muted"><span class="text-warning">•</span>{note}</p>
			{/each}
		</div>
	{/if}
</Panel>
