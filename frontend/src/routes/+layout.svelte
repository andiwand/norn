<script lang="ts">
	import './layout.css';
	import { page } from '$app/state';
	import { store } from '#lib/state.svelte.js';
	import Logo from '#lib/components/Logo.svelte';
	import Toasts from '#lib/components/Toasts.svelte';
	import Cctv from '@lucide/svelte/icons/cctv';
	import Film from '@lucide/svelte/icons/film';
	import Settings from '@lucide/svelte/icons/settings';
	import Plane from '@lucide/svelte/icons/plane';
	import House from '@lucide/svelte/icons/house';
	import { api } from '#lib/api.js';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import type { LayoutProps } from './$types';

	let { children }: LayoutProps = $props();

	// Away mode on or off at once. Off also ends a planned absence that is running now.
	let switching = $state(false);
	async function toggleAway() {
		const away = store.info?.away;
		if (!away || switching) return;
		// Home also ends a planned absence that is running now; a later one stays planned.
		const now = Date.now();
		const running =
			!!away.start &&
			new Date(away.start).getTime() <= now &&
			(!away.end || now < new Date(away.end).getTime());
		const body = away.now
			? { active: false, ...(running ? { start: null, end: null } : {}) }
			: { active: true };
		switching = true;
		await store.attempt(
			() => api.saveSettings({ away: body }),
			away.now ? 'Welcome home' : 'Away mode on'
		);
		switching = false;
	}

	$effect(() => store.start());

	const nav = [
		{
			href: '/',
			label: 'Live',
			icon: Cctv,
			match: (p: string) => p === '/' || p.startsWith('/cameras')
		},
		{
			href: '/recordings',
			label: 'Recordings',
			icon: Film,
			match: (p: string) => p.startsWith('/recordings')
		},
		{
			href: '/settings',
			label: 'Settings',
			icon: Settings,
			match: (p: string) => p.startsWith('/settings')
		}
	];
	const path = $derived(page.url.pathname);
</script>

<div class="flex min-h-dvh flex-col">
	<header class="sticky top-0 z-30 border-b border-line bg-bg/70 backdrop-blur-xl">
		<div class="mx-auto flex h-16 max-w-[1600px] items-center gap-6 px-4 sm:px-6">
			<a href="/" class="flex items-center gap-2.5 font-semibold tracking-tight">
				<Logo size={30} class="text-text" />
				<span class="text-lg">Norn</span>
			</a>
			<nav class="hidden items-center gap-1 md:flex">
				{#each nav as item (item.href)}
					{@const active = item.match(path)}
					<a
						href={item.href}
						class="flex h-9 items-center gap-2 rounded-xl px-3 text-sm font-medium transition {active
							? 'bg-surface-3 text-text'
							: 'text-muted hover:text-text'}"
						aria-current={active ? 'page' : undefined}
					>
						<item.icon class="size-4" />
						{item.label}
					</a>
				{/each}
			</nav>
			{#if store.info}
				{@const away = store.info.away}
				<button
					class="ml-auto flex h-8 items-center gap-1.5 rounded-full border px-3 text-xs font-medium transition {away.now
						? 'border-accent/50 bg-accent/15 text-accent'
						: 'border-line text-muted hover:text-text'}"
					title={away.now
						? away.end
							? `Away until ${new Date(away.end).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })}`
							: 'Away: detections record at any time'
						: 'Switch on away mode'}
					onclick={toggleAway}
					aria-pressed={away.now}
				>
					{#if away.now}<Plane class="size-3.5" />Away{:else}<House class="size-3.5" />Home{/if}
				</button>
			{/if}
			<div class="flex items-center gap-2 text-xs text-muted {store.info ? '' : 'ml-auto'}">
				<span
					class="size-2 rounded-full {store.connected
						? 'bg-success shadow-[0_0_10px_var(--success)]'
						: 'bg-warning'}"
				></span>
				<span class="hidden sm:inline">{store.connected ? 'Connected' : 'Reconnecting…'}</span>
			</div>
		</div>
		{#if store.info?.config_error}
			<div class="flex items-center gap-2 bg-danger/12 px-4 py-2 text-sm text-danger sm:px-6">
				<TriangleAlert class="size-4 shrink-0" />
				<span class="truncate">config.yaml has an error: {store.info.config_error}</span>
			</div>
		{/if}
	</header>

	<main class="mx-auto w-full max-w-[1600px] flex-1 px-4 pt-6 pb-28 sm:px-6 md:pb-12">
		{@render children()}
	</main>

	<nav
		class="pb-safe fixed inset-x-0 bottom-0 z-30 flex border-t border-line bg-bg/85 pt-1.5 backdrop-blur-xl md:hidden"
	>
		{#each nav as item (item.href)}
			{@const active = item.match(path)}
			<a
				href={item.href}
				class="flex flex-1 flex-col items-center gap-1 py-1 text-[11px] font-medium {active
					? 'text-accent'
					: 'text-muted'}"
				aria-current={active ? 'page' : undefined}
			>
				<item.icon class="size-5" />
				{item.label}
			</a>
		{/each}
	</nav>
</div>

<Toasts />
