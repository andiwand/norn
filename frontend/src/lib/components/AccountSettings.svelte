<script lang="ts">
	// The signed-in user's own account: their password, the devices signed in with it, and the
	// API tokens for webhooks and scripts. Everything here acts at once.
	import { api, type ApiToken, type Device } from '../api';
	import { store } from '../state.svelte';
	import SettingsSection from './SettingsSection.svelte';
	import CircleUser from '@lucide/svelte/icons/circle-user';
	import KeyRound from '@lucide/svelte/icons/key-round';
	import MonitorSmartphone from '@lucide/svelte/icons/monitor-smartphone';
	import Webhook from '@lucide/svelte/icons/webhook';
	import LogOut from '@lucide/svelte/icons/log-out';
	import Copy from '@lucide/svelte/icons/copy';
	import Check from '@lucide/svelte/icons/check';
	import X from '@lucide/svelte/icons/x';

	const user = $derived(store.auth?.user);

	let devices = $state<Device[]>([]);
	let tokens = $state<ApiToken[]>([]);
	async function load() {
		[devices, tokens] = await Promise.all([
			api.devices().catch(() => []),
			api.tokens().catch(() => [])
		]);
	}
	$effect(() => {
		load();
	});

	const ago = (seconds: number) => {
		const minutes = (Date.now() / 1000 - seconds) / 60;
		if (minutes < 10) return 'now';
		if (minutes < 60) return `${Math.round(minutes)} min ago`;
		if (minutes < 48 * 60) return `${Math.round(minutes / 60)} h ago`;
		return new Date(seconds * 1000).toLocaleDateString([], { day: 'numeric', month: 'short' });
	};

	// Password
	let current = $state('');
	let next = $state('');
	let changing = $state(false);
	async function changePassword(e: SubmitEvent) {
		e.preventDefault();
		changing = true;
		const ok = await store.attempt(
			() => api.changePassword(current, next).then(() => true),
			'Password changed: your other devices sign in again'
		);
		changing = false;
		if (ok) {
			current = next = '';
			load();
		}
	}

	async function endDevice(d: Device) {
		if (await store.attempt(() => api.endDevice(d.id).then(() => true), `${d.device} signed out`))
			load();
	}

	// Tokens: the new one's secret shows once.
	let tokenName = $state('');
	let fresh = $state<ApiToken | null>(null);
	let copied = $state(false);
	async function newToken(e: SubmitEvent) {
		e.preventDefault();
		const made = await store.attempt(() => api.newToken(tokenName.trim()));
		if (made) {
			fresh = made;
			tokenName = '';
			load();
		}
	}
	async function copy(text: string) {
		await navigator.clipboard?.writeText(text);
		copied = true;
		setTimeout(() => (copied = false), 1500);
	}
	async function removeToken(t: ApiToken) {
		if (await store.attempt(() => api.removeToken(t.id).then(() => true), `“${t.name}” removed`)) {
			if (fresh?.id === t.id) fresh = null;
			load();
		}
	}
	const row = 'flex items-center gap-3 px-5 py-3';
</script>

{#if user}
	<SettingsSection title="Your account" icon={CircleUser}>
		<div class={row}>
			<span class="min-w-0 flex-1">
				<span class="block text-sm font-medium"
					>{user.name}<span
						class="ml-2 badge {user.role === 'admin'
							? 'bg-accent/15 text-accent'
							: 'bg-surface-3 text-muted'}">{user.role === 'admin' ? 'Admin' : 'Viewer'}</span
					></span
				>
				<span class="block text-xs text-muted"
					>{user.role === 'admin'
						? 'Changes everything, and adds and removes users.'
						: 'Watches live and recorded video, steers, records a clip, keeps recordings and switches away mode.'}</span
				>
			</span>
			<button class="btn-ghost h-9 shrink-0" onclick={() => store.signOut()}
				><LogOut class="size-4" />Sign out</button
			>
		</div>
	</SettingsSection>

	<SettingsSection title="Password" icon={KeyRound}>
		<form
			class="grid gap-3 px-5 py-4 sm:grid-cols-[1fr_1fr_auto] sm:items-end"
			onsubmit={changePassword}
		>
			<label class="block">
				<span class="label">Current password</span>
				<input
					class="input"
					type="password"
					bind:value={current}
					autocomplete="current-password"
					required
				/>
			</label>
			<label class="block">
				<span class="label">New password</span>
				<input
					class="input"
					type="password"
					bind:value={next}
					autocomplete="new-password"
					minlength="8"
					required
				/>
			</label>
			<button class="btn-primary" disabled={changing || !current || next.length < 8}
				>{changing ? 'Changing…' : 'Change'}</button
			>
		</form>
		<p class="px-5 pb-4 text-xs text-muted">
			At least 8 characters. Your other devices then sign in again.
		</p>
	</SettingsSection>

	<SettingsSection
		title="Signed-in devices"
		description="Each stays signed in while it's used at least once a month."
		icon={MonitorSmartphone}
	>
		{#each devices as d (d.id)}
			<div class={row}>
				<span class="min-w-0 flex-1">
					<span class="block text-sm font-medium"
						>{d.device}{#if d.current}<span class="ml-2 badge bg-accent/15 text-accent"
								>This one</span
							>{/if}</span
					>
					<span class="block text-xs text-muted">Used {ago(d.seen)} · since {ago(d.created)}</span>
				</span>
				{#if !d.current}
					<button class="btn-ghost h-9" onclick={() => endDevice(d)}>Sign out</button>
				{/if}
			</div>
		{/each}
	</SettingsSection>

	<SettingsSection
		title="API tokens"
		description="For webhooks and scripts, like a doorbell starting a clip: send it as “Authorization: Bearer <token>”. It acts as you, with your role."
		icon={Webhook}
	>
		{#if fresh?.token}
			<div class="bg-accent/8 px-5 py-4">
				<p class="text-sm font-medium">“{fresh.name}”: copy it now, it isn't shown again.</p>
				<div class="mt-2 flex items-center gap-2">
					<code class="min-w-0 flex-1 truncate rounded-lg bg-surface-2 px-3 py-2 font-mono text-xs"
						>{fresh.token}</code
					>
					<button
						class="icon-btn size-9 shrink-0"
						aria-label="Copy the token"
						onclick={() => copy(fresh?.token ?? '')}
						>{#if copied}<Check class="size-4 text-success" />{:else}<Copy
								class="size-4"
							/>{/if}</button
					>
				</div>
			</div>
		{/if}
		{#each tokens as t (t.id)}
			<div class={row}>
				<span class="min-w-0 flex-1">
					<span class="block truncate text-sm font-medium">{t.name}</span>
					<span class="block text-xs text-muted"
						>Made {ago(t.created)} · {t.used ? `used ${ago(t.used)}` : 'not used yet'}</span
					>
				</span>
				<button
					class="icon-btn size-9"
					aria-label="Remove “{t.name}”"
					onclick={() => removeToken(t)}><X class="size-4" /></button
				>
			</div>
		{/each}
		<form class="flex gap-2 px-5 py-4" onsubmit={newToken}>
			<input
				class="input h-10"
				bind:value={tokenName}
				placeholder="What it's for, e.g. Doorbell"
				maxlength="60"
				required
			/>
			<button class="btn-ghost h-10 shrink-0" disabled={!tokenName.trim()}>New token</button>
		</form>
	</SettingsSection>
{/if}
