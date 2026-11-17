<script lang="ts">
	// All cameras and circles: what they are, how they are doing, and a way into each.
	import { goto } from '$app/navigation';
	import { store } from '#lib/state.svelte.js';
	import type { Camera } from '#lib/api.js';
	import Plus from '@lucide/svelte/icons/plus';
	import Pencil from '@lucide/svelte/icons/pencil';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import Cctv from '@lucide/svelte/icons/cctv';
	import Users from '@lucide/svelte/icons/users';

	function status(c: Camera): [string, string] {
		if (!c.enabled) return ['Disabled', 'text-muted'];
		if (c.error) return ['Error', 'text-danger'];
		if (c.device && !c.device.online) return ['Offline', 'text-danger'];
		if (c.firmware?.status === 'update') return ['Update available', 'text-accent'];
		if (c.device) return ['OK', 'text-success'];
		return ['…', 'text-muted'];
	}
	const model = (c: Camera) =>
		[c.device?.manufacturer, c.device?.model].filter(Boolean).join(' ') || c.driver;
	const row =
		'group flex cursor-pointer items-center gap-4 px-5 py-3.5 transition hover:bg-surface-2 focus-visible:bg-surface-2 focus-visible:outline-none';
</script>

<svelte:head><title>Cameras · Norn</title></svelte:head>

<div class="mx-auto max-w-3xl space-y-5">
	<div class="flex flex-wrap items-end justify-between gap-3">
		<div>
			<h1 class="page-title">Cameras</h1>
			<p class="page-intro">Open a camera to watch and steer it, or edit how Norn reaches it.</p>
		</div>
		<a href="/cameras/new" class="btn-primary"><Plus class="size-4" />Add camera</a>
	</div>

	<section class="overflow-hidden card">
		<header class="flex items-center gap-2 border-b border-line px-5 py-3 text-muted">
			<Cctv class="size-4" /><span class="eyebrow">Cameras</span>
			<span class="ml-auto text-xs">{store.cameras.length}</span>
		</header>
		<ul class="divide-y divide-line">
			{#each store.cameras as c (c.id)}
				{@const [text, tone] = status(c)}
				<li>
					<!-- The whole row opens the camera; Edit is its own button. -->
					<div
						class={row}
						role="link"
						tabindex="0"
						onclick={() => goto(`/cameras/${c.id}`)}
						onkeydown={(e) => e.key === 'Enter' && goto(`/cameras/${c.id}`)}
					>
						<span class="min-w-0 flex-1">
							<span class="block truncate font-medium group-hover:text-accent">{c.name}</span>
							<span class="block truncate text-xs text-muted"
								>{model(c)}{#if c.device?.firmware}<span class="font-mono">
										· {c.device.firmware}</span
									>{/if}</span
							>
						</span>
						<span class="shrink-0 text-xs {tone}">{text}</span>
						<a
							href="/cameras/{c.id}/edit"
							class="icon-btn size-8 shrink-0"
							aria-label="Edit {c.name}"
							title="Edit"
							onclick={(e) => e.stopPropagation()}><Pencil class="size-4" /></a
						>
						<ChevronRight
							class="size-4 shrink-0 text-muted transition group-hover:translate-x-0.5"
						/>
					</div>
				</li>
			{:else}
				<li class="px-5 py-8 text-center text-sm text-muted">No cameras yet.</li>
			{/each}
		</ul>
	</section>

	<section class="overflow-hidden card">
		<header class="flex items-center gap-2 border-b border-line px-5 py-3 text-muted">
			<Users class="size-4" /><span class="eyebrow">Circles</span>
			<a href="/circles/new" class="ml-auto chip"><Plus class="size-3.5" />Circle</a>
		</header>
		<p class="border-b border-line px-5 py-3 text-xs text-muted">
			Groups of cameras that share settings, record together, and can be steered at once.
		</p>
		<ul class="divide-y divide-line">
			{#each store.circles as circle (circle.id)}
				<li>
					<a href="/circles/{circle.id}" class={row}>
						<span class="min-w-0 flex-1">
							<span class="block truncate font-medium group-hover:text-accent">{circle.name}</span>
							<span class="block truncate text-xs text-muted"
								>{circle.cameras.map((id) => store.camera(id)?.name ?? id).join(', ')}</span
							>
						</span>
						<ChevronRight
							class="size-4 shrink-0 text-muted transition group-hover:translate-x-0.5"
						/>
					</a>
				</li>
			{:else}
				<li class="px-5 py-6 text-center text-sm text-muted">No circles yet.</li>
			{/each}
		</ul>
	</section>
</div>
