<script lang="ts">
	import './layout.css';
	import { page } from '$app/state';
	import { store } from '#lib/state.svelte.js';
	import Logo from '#lib/components/Logo.svelte';
	import Toasts from '#lib/components/Toasts.svelte';
	import HeaderGauges from '#lib/components/HeaderGauges.svelte';
	import { install } from '#lib/install.svelte.js';
	import Download from '@lucide/svelte/icons/download';
	import Cctv from '@lucide/svelte/icons/cctv';
	import Film from '@lucide/svelte/icons/film';
	import Settings from '@lucide/svelte/icons/settings';
	import Plane from '@lucide/svelte/icons/plane';
	import Zap from '@lucide/svelte/icons/zap';
	import House from '@lucide/svelte/icons/house';
	import Video from '@lucide/svelte/icons/video';
	import Activity from '@lucide/svelte/icons/activity';
	import CircleHelp from '@lucide/svelte/icons/circle-help';
	import { api } from '#lib/api.js';
	import { serverTime } from '#lib/format.js';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import type { LayoutProps } from './$types';

	let { children }: LayoutProps = $props();

	// Away mode on or off at once. Off also ends a planned absence that is running now.
	let switching = $state(false);
	async function toggleAway() {
		const info = store.info;
		const away = info?.away;
		if (!info || !away || switching) return;
		// Home also ends a planned absence that is running now; a later one stays planned. Its
		// times are on the server's clock.
		const now = Date.now();
		const at = (local: string) => serverTime(local, info.time.offset_minutes);
		const running = !!away.start && at(away.start) <= now && (!away.end || now < at(away.end));
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

	// A camera's own page belongs to Live; the list, adding and editing to Cameras.
	const cameraPage = (p: string) => /^\/cameras\/[^/]+$/.test(p) && p !== '/cameras/new';
	const nav = [
		{ href: '/', label: 'Live', icon: Cctv, match: (p: string) => p === '/' || cameraPage(p) },
		{
			href: '/recordings',
			label: 'Recordings',
			icon: Film,
			match: (p: string) => p.startsWith('/recordings')
		},
		{
			href: '/cameras',
			label: 'Cameras',
			icon: Video,
			match: (p: string) => (p.startsWith('/cameras') && !cameraPage(p)) || p.startsWith('/circles')
		},
		{ href: '/away', label: 'Away', icon: Plane, match: (p: string) => p.startsWith('/away') },
		{
			href: '/triggers',
			label: 'Triggers',
			icon: Zap,
			match: (p: string) => p.startsWith('/triggers')
		},
		{
			href: '/settings',
			label: 'Settings',
			icon: Settings,
			match: (p: string) => p.startsWith('/settings')
		},
		// Not in the phone's bottom bar: Settings links to them there.
		{
			href: '/diagnostics',
			label: 'Diagnostics',
			icon: Activity,
			match: (p: string) => p.startsWith('/diagnostics'),
			desktop: true
		},
		{
			href: '/help',
			label: 'Help',
			icon: CircleHelp,
			match: (p: string) => p.startsWith('/help'),
			desktop: true
		}
	];
	const path = $derived(page.url.pathname);
</script>

<div class="flex min-h-dvh flex-col">
	<header class="sticky top-0 z-30 border-b border-line bg-bg/70 backdrop-blur-xl">
		<div
			class="mx-auto flex h-12 max-w-[1600px] items-center gap-2 px-4 sm:gap-3 sm:px-6 md:h-14 xl:gap-5"
		>
			<div class="flex shrink-0">
				<a href="/" class="flex shrink-0 items-center gap-2.5 font-semibold tracking-tight">
					<Logo size={26} class="text-text" />
					<span class="hidden text-lg min-[360px]:inline">Norn</span>
				</a>
			</div>
			<!-- The nav sits in the middle of the room between the logo and the controls. -->
			<nav class="hidden min-w-0 flex-1 items-center justify-center gap-0.5 md:flex">
				{#each nav as item (item.href)}
					{@const active = item.match(path)}
					<a
						href={item.href}
						class="flex h-9 items-center gap-2 rounded-xl px-3 text-sm font-medium transition {active
							? 'bg-surface-3 text-text'
							: 'text-muted hover:text-text'}"
						aria-current={active ? 'page' : undefined}
						title={item.label}
					>
						<item.icon class="size-4" />
						<span class="hidden xl:inline">{item.label}</span>
					</a>
				{/each}
			</nav>
			<div class="ml-auto flex shrink-0 items-center gap-2 sm:gap-3 xl:gap-5">
				{#if store.info}
					{@const away = store.info.away}
					<!-- Home or away, as a switch: the knob sits on the house or the plane. -->
					<button
						role="switch"
						aria-checked={away.now}
						aria-label="Away mode"
						class="relative flex h-8 w-16 shrink-0 items-center justify-between rounded-full border px-2 transition disabled:opacity-60 {away.now
							? 'border-accent/50 bg-accent/20'
							: 'border-line bg-surface-2'}"
						title={away.now
							? away.end
								? `Away until ${new Date(away.end).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })}. Switch off when you're home.`
								: 'Away: detections record at any time. Switch off when you are home.'
							: 'Home. Switch on away mode when you leave.'}
						onclick={toggleAway}
						disabled={switching}
					>
						<span
							class="absolute top-0.5 left-0.5 size-[26px] rounded-full shadow transition-transform {away.now
								? 'translate-x-8 bg-accent'
								: 'bg-surface'}"
						></span>
						<House class="relative size-3.5 {away.now ? 'text-muted' : 'text-text'}" />
						<Plane class="relative size-3.5 {away.now ? 'text-accent-ink' : 'text-muted'}" />
					</button>
				{/if}
				<!-- Install: the browser's own dialog where it offers one, else how to do it. -->
				{#if install.offered && !install.installed}
					<button
						class="icon-btn size-8 shrink-0 text-muted"
						onclick={() => install.install()}
						title="Install Norn as an app"
						aria-label="Install Norn as an app"><Download class="size-4" /></button
					>
				{:else if !install.installed}
					<a
						href="/help#install"
						class="icon-btn size-8 shrink-0 text-muted"
						title="How to install Norn as an app"
						aria-label="How to install Norn as an app"><Download class="size-4" /></a
					>
				{/if}
				<HeaderGauges />
				<!-- Connected: just the dot; only trouble gets words. -->
				<div
					class="flex shrink-0 items-center gap-2 text-xs text-muted"
					title={store.connected ? 'Connected' : 'Reconnecting…'}
				>
					<span
						class="size-2 rounded-full {store.connected
							? 'bg-success shadow-[0_0_10px_var(--success)]'
							: 'bg-warning'}"
					></span>
					{#if !store.connected}<span class="hidden sm:inline">Reconnecting…</span>{/if}
				</div>
			</div>
		</div>
		{#if store.info?.config_error}
			<div class="flex items-center gap-2 bg-danger/12 px-4 py-2 text-sm text-danger sm:px-6">
				<TriangleAlert class="size-4 shrink-0" />
				<span class="truncate">config.yaml has an error: {store.info.config_error}</span>
			</div>
		{/if}
	</header>

	<main class="mx-auto w-full max-w-[1600px] flex-1 px-3 pt-3 pb-24 sm:px-6 sm:pt-6 md:pb-12">
		{@render children()}
	</main>

	<nav
		class="pb-safe fixed inset-x-0 bottom-0 z-30 flex border-t border-line bg-bg/85 pt-1.5 backdrop-blur-xl md:hidden"
	>
		{#each nav.filter((item) => !item.desktop) as item (item.href)}
			{@const active = item.match(path)}
			<a
				href={item.href}
				class="flex flex-1 flex-col items-center gap-0.5 py-0.5 text-[10px] font-medium {active
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
