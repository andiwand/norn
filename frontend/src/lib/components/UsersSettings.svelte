<script lang="ts">
	// Who may sign in. Off until the first user (an admin) is made here; then everyone signs
	// in, at home too. Admins add people as admins or viewers, set new passwords and remove
	// them. Everything here acts at once.
	import { api, type Role, type User } from '../api';
	import { store } from '../state.svelte';
	import SettingsSection from './SettingsSection.svelte';
	import Users from '@lucide/svelte/icons/users';
	import ShieldCheck from '@lucide/svelte/icons/shield-check';
	import UserPlus from '@lucide/svelte/icons/user-plus';
	import X from '@lucide/svelte/icons/x';

	const enabled = $derived(!!store.auth?.enabled);
	let users = $state<User[]>([]);
	async function load() {
		users = enabled ? await api.users().catch(() => []) : [];
	}
	$effect(() => {
		void enabled;
		load();
	});

	const ROLES: [Role, string][] = [
		['viewer', 'Viewer'],
		['admin', 'Admin']
	];
	const nameHint = 'Lowercase letters, digits and dashes, like anna or jo-2';
	const clean = (n: string) => n.trim().toLowerCase();

	// The first user: turns sign-in on, as an admin, signed in here.
	let firstName = $state('');
	let firstPassword = $state('');
	let firstAgain = $state('');
	let busy = $state(false);
	async function turnOn(e: SubmitEvent) {
		e.preventDefault();
		busy = true;
		const user = await store.attempt(
			() => api.firstUser(clean(firstName), firstPassword),
			'Sign-in is on: you are the first admin'
		);
		busy = false;
		if (user) {
			firstName = firstPassword = firstAgain = '';
			store.signedIn(user);
		}
	}

	// Adding someone
	let name = $state('');
	let password = $state('');
	let role = $state<Role>('viewer');
	async function add(e: SubmitEvent) {
		e.preventDefault();
		busy = true;
		const user = await store.attempt(
			() => api.addUser(clean(name), password, role),
			`Added ${clean(name)}: tell them the password`
		);
		busy = false;
		if (user) {
			name = password = '';
			role = 'viewer';
			load();
		}
	}

	async function setRole(u: User, next: Role) {
		if (next === u.role) return;
		if (
			await store.attempt(
				() => api.changeUser(u.name, { role: next }),
				`${u.name} is now ${next === 'admin' ? 'an admin' : 'a viewer'}`
			)
		) {
			load();
			if (u.you) store.signedIn({ name: u.name, role: next });
		}
	}

	// A new password for someone (they forgot theirs): a second step asks for it.
	let resetting = $state<string | null>(null);
	let newPassword = $state('');
	async function reset(e: SubmitEvent, u: User) {
		e.preventDefault();
		const ok = await store.attempt(
			() => api.changeUser(u.name, { password: newPassword }).then(() => true),
			`New password for ${u.name}: their devices sign in again`
		);
		if (ok) {
			resetting = null;
			newPassword = '';
			load();
		}
	}

	// Removing takes a second click within a few seconds.
	let confirming = $state<string | null>(null);
	let timer: ReturnType<typeof setTimeout> | undefined;
	async function remove(u: User) {
		clearTimeout(timer);
		if (confirming !== u.name) {
			confirming = u.name;
			timer = setTimeout(() => (confirming = null), 3000);
			return;
		}
		confirming = null;
		if (await store.attempt(() => api.removeUser(u.name).then(() => true), `Removed ${u.name}`)) {
			if (u.you) store.signOut();
			else load();
		}
	}
</script>

{#if !enabled}
	<SettingsSection
		title="Sign-in"
		description="Off: Norn trusts everyone who reaches it. Turn it on before you open Norn to the internet (through a reverse proxy with HTTPS): then everyone signs in, at home too, and you add the others as admins or viewers."
		icon={ShieldCheck}
	>
		<form class="divide-y divide-line" onsubmit={turnOn}>
			<div class="grid gap-3 px-5 py-4 sm:grid-cols-3 sm:items-end">
				<label class="block">
					<span class="label">Your name</span>
					<input
						class="input"
						bind:value={firstName}
						autocomplete="username"
						autocapitalize="none"
						spellcheck="false"
						placeholder="anna"
						title={nameHint}
						required
					/>
				</label>
				<label class="block">
					<span class="label">Password</span>
					<input
						class="input"
						type="password"
						bind:value={firstPassword}
						autocomplete="new-password"
						minlength="8"
						required
					/>
				</label>
				<label class="block">
					<span class="label">Again</span>
					<input
						class="input"
						type="password"
						bind:value={firstAgain}
						autocomplete="new-password"
						required
					/>
				</label>
			</div>
			<div class="flex flex-wrap items-center justify-end gap-3 px-5 py-4">
				<span
					class="mr-auto text-xs {firstAgain && firstAgain !== firstPassword
						? 'text-danger'
						: 'text-muted'}"
				>
					{firstAgain && firstAgain !== firstPassword
						? "The passwords don't match"
						: 'You become the first admin, signed in here.'}
				</span>
				<button
					class="btn-primary"
					disabled={busy ||
						!clean(firstName) ||
						firstPassword.length < 8 ||
						firstPassword !== firstAgain}><ShieldCheck class="size-4" />Turn on sign-in</button
				>
			</div>
		</form>
	</SettingsSection>
{:else}
	<SettingsSection
		title="Users"
		description="Admins change everything. Viewers watch live and recorded video, steer, record a clip, keep recordings and switch away mode."
		icon={Users}
	>
		{#each users as u (u.name)}
			<div class="flex flex-wrap items-center gap-3 px-5 py-3">
				<span class="min-w-0 flex-1 basis-40">
					<span class="block text-sm font-medium"
						>{u.name}{#if u.you}<span class="ml-2 badge bg-accent/15 text-accent">You</span
							>{/if}</span
					>
					<span class="block text-xs text-muted"
						>{u.devices}
						{u.devices === 1 ? 'device' : 'devices'} signed in{u.tokens
							? ` · ${u.tokens} ${u.tokens === 1 ? 'token' : 'tokens'}`
							: ''}</span
					>
				</span>
				<div
					class="flex rounded-xl bg-surface-3 p-1"
					role="radiogroup"
					aria-label="Role of {u.name}"
				>
					{#each ROLES as [r, label] (r)}
						<button
							role="radio"
							aria-checked={u.role === r}
							class="rounded-lg px-2.5 py-1 text-xs font-medium transition {u.role === r
								? 'bg-surface text-text shadow'
								: 'text-muted hover:text-text'}"
							onclick={() => setRole(u, r)}>{label}</button
						>
					{/each}
				</div>
				<!-- Your own password is changed under Account; the space stays, so the rows line up. -->
				<button
					class="btn-ghost h-9 {u.you ? 'invisible' : ''}"
					tabindex={u.you ? -1 : undefined}
					aria-hidden={u.you}
					onclick={() => (resetting = resetting === u.name ? null : u.name)}>New password</button
				>
				<button
					class="h-9 rounded-xl px-2.5 text-sm font-medium transition {confirming === u.name
						? 'bg-danger text-white'
						: 'text-muted hover:bg-surface-3 hover:text-danger'}"
					aria-label={confirming === u.name ? `Really remove ${u.name}` : `Remove ${u.name}`}
					onclick={() => remove(u)}
					>{#if confirming === u.name}Remove?{:else}<X class="size-4" />{/if}</button
				>
				{#if resetting === u.name}
					<form class="flex w-full gap-2" onsubmit={(e) => reset(e, u)}>
						<input
							class="input h-10"
							type="password"
							bind:value={newPassword}
							autocomplete="new-password"
							placeholder="A new password for {u.name}"
							minlength="8"
							required
						/>
						<button class="btn-primary h-10 shrink-0" disabled={newPassword.length < 8}>Set</button>
					</form>
				{/if}
			</div>
		{/each}
	</SettingsSection>

	<SettingsSection title="Add someone" icon={UserPlus}>
		<form class="grid gap-3 px-5 py-4 sm:grid-cols-[1fr_1fr_auto_auto] sm:items-end" onsubmit={add}>
			<label class="block">
				<span class="label">Name</span>
				<input
					class="input"
					bind:value={name}
					autocomplete="off"
					autocapitalize="none"
					spellcheck="false"
					placeholder="ben"
					title={nameHint}
					required
				/>
			</label>
			<label class="block">
				<span class="label">Password</span>
				<input
					class="input"
					type="password"
					bind:value={password}
					autocomplete="new-password"
					minlength="8"
					required
				/>
			</label>
			<div>
				<span class="label">Role</span>
				<div
					class="flex h-11 items-center rounded-xl bg-surface-3 p-1"
					role="radiogroup"
					aria-label="Role"
				>
					{#each ROLES as [r, label] (r)}
						<button
							type="button"
							role="radio"
							aria-checked={role === r}
							class="h-full rounded-lg px-3 text-sm font-medium transition {role === r
								? 'bg-surface text-text shadow'
								: 'text-muted hover:text-text'}"
							onclick={() => (role = r)}>{label}</button
						>
					{/each}
				</div>
			</div>
			<button class="btn-primary h-11" disabled={busy || !clean(name) || password.length < 8}
				>Add</button
			>
		</form>
		<p class="px-5 pb-4 text-xs text-muted">{nameHint}. Passwords: at least 8 characters.</p>
	</SettingsSection>
{/if}
