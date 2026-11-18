<script lang="ts">
	// Settings → Notifications: this device (turn them on, with the browser's permission, and
	// why it may not work here), when phones get one (saved with the rest of the settings), and
	// the devices that get them.
	import { onMount } from 'svelte';
	import { api, type NotificationSettings, type PushDevice } from '../api';
	import { push } from '../push.svelte';
	import { store } from '../state.svelte';
	import SettingsSection from './SettingsSection.svelte';
	import ChoiceSetting from './ChoiceSetting.svelte';
	import TriggerSetting from './TriggerSetting.svelte';
	import ScheduleSetting from './ScheduleSetting.svelte';
	import NumberSetting from './NumberSetting.svelte';
	import BellRing from '@lucide/svelte/icons/bell-ring';
	import Bell from '@lucide/svelte/icons/bell';
	import Smartphone from '@lucide/svelte/icons/smartphone';
	import Send from '@lucide/svelte/icons/send';
	import Pencil from '@lucide/svelte/icons/pencil';
	import X from '@lucide/svelte/icons/x';
	import LoaderCircle from '@lucide/svelte/icons/loader-circle';

	let {
		rules = $bindable(),
		defaults
	}: { rules: NotificationSettings; defaults: NotificationSettings } = $props();

	let failed = $state('');
	onMount(() => {
		push.load().catch((e) => (failed = e instanceof Error ? e.message : String(e)));
	});

	async function enable() {
		const ok = await store.attempt(() => push.enable());
		if (ok === undefined || !push.device) return;
		// The proof that it works: one right away.
		await store.attempt(
			() => api.testDevice(push.device!.id),
			'Notifications on: a test is on its way'
		);
	}

	async function test(device: PushDevice) {
		await store.attempt(() => api.testDevice(device.id), `A test to ${device.name} is on its way`);
	}

	// Removing someone else's device takes a second tap.
	let confirming = $state<string | null>(null);
	let confirmTimer: ReturnType<typeof setTimeout> | undefined;
	async function remove(device: PushDevice) {
		clearTimeout(confirmTimer);
		if (confirming !== device.id) {
			confirming = device.id;
			confirmTimer = setTimeout(() => (confirming = null), 3000);
			return;
		}
		confirming = null;
		await store.attempt(() => push.remove(device), `${device.name} gets no more notifications`);
	}

	let renaming = $state<string | null>(null);
	let newName = $state('');
	async function rename(device: PushDevice) {
		const name = newName.trim();
		renaming = null;
		if (name && name !== device.name) await store.attempt(() => push.change(device, { name }));
	}

	let choosing = $state<string | null>(null); // the device whose cameras are being picked
	function toggleCamera(device: PushDevice, id: string) {
		const all = store.cameras.map((c) => c.id);
		const now = device.cameras ?? all;
		const next = now.includes(id) ? now.filter((c) => c !== id) : [...now, id];
		store.attempt(() => push.change(device, { cameras: next.length === all.length ? null : next }));
	}

	function toggleRuleCamera(id: string) {
		const all = store.cameras.map((c) => c.id);
		const now = rules.cameras.length ? rules.cameras : all;
		const next = now.includes(id) ? now.filter((c) => c !== id) : [...now, id];
		rules.cameras = next.length === all.length ? [] : next;
	}

	const nameOf = (id: string) => store.camera(id)?.name ?? id;
	const when = (seconds: number | null) =>
		seconds
			? new Date(seconds * 1000).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })
			: 'not yet';
	const ON_OFF: [boolean, string][] = [
		[true, 'On'],
		[false, 'Off']
	];
</script>

<SettingsSection
	title="This device"
	description="A notification on this phone or computer when something is detected, with the camera's picture."
	icon={Smartphone}
>
	{#snippet aside()}
		{#if push.device}
			<span class="badge bg-success/15 text-success">On</span>
		{:else if push.support === 'ok'}
			<span class="badge bg-surface-3 text-muted">Off</span>
		{/if}
	{/snippet}
	<div class="flex flex-wrap items-center gap-3 px-5 py-4">
		{#if push.support === 'checking'}
			<LoaderCircle class="size-4 animate-spin text-muted" />
		{:else if push.support === 'insecure'}
			<p class="min-w-0 flex-1 basis-64 text-sm text-muted">
				Notifications need Norn's <strong class="text-text">https://</strong> address: browsers
				allow them only over HTTPS. Open Norn through your reverse proxy (for example
				<code class="font-mono text-xs">tailscale serve</code> or Caddy) and turn them on there.
			</p>
		{:else if push.support === 'ios-browser'}
			<p class="min-w-0 flex-1 basis-64 text-sm text-muted">
				On iPhone and iPad only the installed app gets notifications (iOS 16.4 or newer): tap Share,
				then <strong class="text-text">Add to Home Screen</strong>, open Norn from the home screen
				and turn them on there.
				<a href="/help#install" class="text-accent hover:underline">How to install</a>
			</p>
		{:else if push.support === 'unsupported'}
			<p class="min-w-0 flex-1 basis-64 text-sm text-muted">
				This browser can't get notifications. Chrome, Edge, Firefox and Safari can.
			</p>
		{:else if push.support === 'denied'}
			<p class="min-w-0 flex-1 basis-64 text-sm text-muted">
				Notifications are blocked for this site. Allow them in the browser's site settings (the icon
				left of the address), then reload this page.
			</p>
		{:else if push.device}
			<p class="min-w-0 flex-1 basis-64 text-sm text-muted">
				<span class="font-medium text-text">{push.device.name}</span> gets notifications, as set below.
			</p>
			<button class="btn-ghost h-9" onclick={() => push.device && test(push.device)}
				><Send class="size-4" />Send a test</button
			>
			<button
				class="btn-ghost h-9"
				disabled={push.busy}
				onclick={() => store.attempt(() => push.disable(), 'Notifications off here')}
				>Turn off</button
			>
		{:else}
			<p class="min-w-0 flex-1 basis-64 text-sm text-muted">
				The browser asks whether Norn may send notifications.
			</p>
			<button class="btn-primary h-9" disabled={push.busy} onclick={enable}
				>{#if push.busy}<LoaderCircle class="size-4 animate-spin" />{:else}<BellRing
						class="size-4"
					/>{/if}Turn on</button
			>
		{/if}
		{#if failed}<p class="w-full text-xs text-danger">{failed}</p>{/if}
	</div>
</SettingsSection>

<SettingsSection
	title="When"
	description={store.isAdmin
		? "For all devices, whether the detection records or not. With “Only if Norn agrees” (on Triggers), a camera's own alarm notifies once Norn's AI confirms it."
		: 'For all devices. An admin sets these.'}
	icon={Bell}
>
	<!-- A viewer sees the rules; an admin changes them. -->
	<fieldset disabled={!store.isAdmin} class="contents">
		<ChoiceSetting label="Notifications" bind:value={rules.enabled} choices={ON_OFF} />
		{#if rules.enabled}
			<TriggerSetting
				label="For"
				hint="What is detected."
				bind:value={
					() => rules.kinds,
					(v) => {
						rules.kinds = v ?? [];
					}
				}
			/>
			<div
				class="@container flex flex-wrap items-center justify-between gap-x-6 gap-y-2 px-5 py-3.5"
			>
				<div class="min-w-0 flex-1 basis-56">
					<span class="block text-sm font-medium">Cameras</span>
					<span class="mt-0.5 block text-xs text-muted"
						>{rules.cameras.length ? 'Only these.' : 'All of them.'}</span
					>
				</div>
				<div class="flex w-full shrink-0 flex-wrap items-center justify-end gap-1.5 @[33rem]:w-60">
					{#each store.cameras as c (c.id)}
						{@const on = !rules.cameras.length || rules.cameras.includes(c.id)}
						<button
							type="button"
							class="chip {on ? 'chip-active' : ''}"
							aria-pressed={on}
							onclick={() => toggleRuleCamera(c.id)}>{c.name}</button
						>
					{/each}
				</div>
			</div>
			<ChoiceSetting
				label="While"
				bind:value={rules.away_only}
				choices={[
					[false, 'Always'],
					[true, 'Only while away']
				]}
			/>
			<ScheduleSetting
				label="Quiet hours"
				hint="No notifications in these times (detections still record)."
				bind:value={
					() => rules.quiet,
					(v) => {
						rules.quiet = v ?? [];
					}
				}
				empty="None."
			/>
			<NumberSetting
				label="At most every"
				hint="One notification per camera; what it detects meanwhile stays quiet. 0: each time."
				bind:value={rules.every_minutes}
				fallback={defaults.every_minutes}
				max={1440}
				unit="min"
			/>
			<ChoiceSetting
				label="Picture"
				hint="The camera's picture at that moment. Android shows it; iPhones show none in notifications."
				bind:value={rules.picture}
				choices={ON_OFF}
			/>
		{/if}
	</fieldset>
</SettingsSection>

<SettingsSection title="Devices" description="Phones and browsers that get notifications.">
	{#if !push.devices.length}
		<p class="px-5 py-4 text-sm text-muted">
			None yet. Turn notifications on above, on each device.
		</p>
	{/if}
	{#each push.devices as device (device.id)}
		{@const mine = push.device?.id === device.id}
		<div class="px-5 py-3.5">
			<div class="flex flex-wrap items-center gap-x-3 gap-y-2">
				<div class="min-w-0 flex-1 basis-48">
					{#if renaming === device.id}
						<form
							onsubmit={(e) => {
								e.preventDefault();
								rename(device);
							}}
						>
							<!-- svelte-ignore a11y_autofocus -->
							<input
								class="input h-9"
								bind:value={newName}
								maxlength="60"
								autofocus
								aria-label="Name"
								onblur={() => rename(device)}
								onkeydown={(e) => e.key === 'Escape' && (renaming = null)}
							/>
						</form>
					{:else}
						<span class="flex items-center gap-2 text-sm font-medium">
							<span class="truncate">{device.name}</span>
							{#if mine}<span class="badge bg-accent/15 text-accent">This device</span>{/if}
						</span>
						<span class="mt-0.5 block text-xs text-muted">
							Last notification {when(device.last_used)}{#if device.user}
								· {device.user}{/if}
						</span>
					{/if}
				</div>
				<button
					class="chip"
					aria-expanded={choosing === device.id}
					onclick={() => (choosing = choosing === device.id ? null : device.id)}
					>{device.cameras
						? `${device.cameras.length} of ${store.cameras.length} cameras`
						: 'All cameras'}</button
				>
				<div class="flex items-center gap-1">
					<button
						class="icon-btn size-9"
						title="Rename"
						aria-label="Rename {device.name}"
						onclick={() => {
							newName = device.name;
							renaming = device.id;
						}}><Pencil class="size-4" /></button
					>
					<button
						class="icon-btn size-9"
						title="Send a test"
						aria-label="Send a test to {device.name}"
						onclick={() => test(device)}><Send class="size-4" /></button
					>
					<button
						class="icon-btn size-9 {confirming === device.id
							? 'w-auto! bg-danger px-2 text-xs font-medium text-white'
							: 'hover:text-danger'}"
						title="Remove: it gets no more notifications"
						aria-label={confirming === device.id
							? `Really remove ${device.name}`
							: `Remove ${device.name}`}
						onclick={() => (mine ? push.disable() : remove(device))}
						>{#if confirming === device.id}Remove?{:else}<X class="size-4" />{/if}</button
					>
				</div>
			</div>
			{#if choosing === device.id}
				<div class="mt-2 flex flex-wrap gap-1.5" role="group" aria-label="Cameras on {device.name}">
					{#each store.cameras as c (c.id)}
						{@const on = !device.cameras || device.cameras.includes(c.id)}
						<button
							class="chip {on ? 'chip-active' : ''}"
							aria-pressed={on}
							onclick={() => toggleCamera(device, c.id)}>{nameOf(c.id)}</button
						>
					{/each}
				</div>
			{/if}
		</div>
	{/each}
</SettingsSection>
