<script lang="ts">
	// The sign-in page: shown instead of the app while sign-in is on and nobody is signed in
	// here. One form; the browser's password manager fills it.
	import { api, ApiError } from '../api';
	import { store } from '../state.svelte';
	import Logo from './Logo.svelte';
	import LogIn from '@lucide/svelte/icons/log-in';
	import Eye from '@lucide/svelte/icons/eye';
	import EyeOff from '@lucide/svelte/icons/eye-off';

	let name = $state('');
	let password = $state('');
	let show = $state(false);
	let busy = $state(false);
	let error = $state('');

	async function submit(e: SubmitEvent) {
		e.preventDefault();
		if (busy) return;
		busy = true;
		error = '';
		try {
			const user = await api.login(name.trim(), password);
			password = '';
			store.signedIn(user);
		} catch (err) {
			error =
				err instanceof ApiError
					? err.message
					: "Norn doesn't answer. Check the connection and try again.";
		} finally {
			busy = false;
		}
	}
</script>

<svelte:head><title>Sign in · Norn</title></svelte:head>

<main class="grid min-h-dvh place-items-center px-4 py-10">
	<div class="w-full max-w-sm">
		<div class="mb-8 flex flex-col items-center gap-3 text-center">
			<Logo size={44} class="text-text" />
			<h1 class="text-2xl font-semibold tracking-tight">Sign in to Norn</h1>
			<p class="text-sm text-muted">Your cameras, live and recorded.</p>
		</div>
		<form class="space-y-4 card p-6" onsubmit={submit}>
			<label class="block">
				<span class="label">Name</span>
				<input
					class="input"
					bind:value={name}
					name="username"
					autocomplete="username"
					autocapitalize="none"
					spellcheck="false"
					required
				/>
			</label>
			<label class="block">
				<span class="label">Password</span>
				<span class="relative block">
					<input
						class="input pr-11"
						type={show ? 'text' : 'password'}
						bind:value={password}
						name="password"
						autocomplete="current-password"
						required
					/>
					<button
						type="button"
						class="absolute inset-y-0 right-0 grid w-11 place-items-center text-muted hover:text-text"
						aria-label={show ? 'Hide the password' : 'Show the password'}
						aria-pressed={show}
						onclick={() => (show = !show)}
						>{#if show}<EyeOff class="size-4" />{:else}<Eye class="size-4" />{/if}</button
					>
				</span>
			</label>
			{#if error}
				<p class="rounded-xl bg-danger/10 px-3 py-2 text-sm text-danger" role="alert">{error}</p>
			{/if}
			<button class="btn-primary w-full" disabled={busy || !name.trim() || !password}>
				<LogIn class="size-4" />{busy ? 'Signing in…' : 'Sign in'}
			</button>
		</form>
		<p class="mt-6 text-center text-xs text-muted">
			Forgot the password? An admin sets a new one in Settings → Users.
		</p>
	</div>
</main>
