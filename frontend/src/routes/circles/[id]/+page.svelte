<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { api, type CircleControl } from '#lib/api.js';
	import { store } from '#lib/state.svelte.js';
	import { byGroup } from '#lib/format.js';
	import CameraTile from '#lib/components/CameraTile.svelte';
	import CircleForm from '#lib/components/CircleForm.svelte';
	import ControlField from '#lib/components/ControlField.svelte';
	import Panel from '#lib/components/Panel.svelte';
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';
	import CircleDot from '@lucide/svelte/icons/circle-dot';
	import Square from '@lucide/svelte/icons/square';
	import Trash2 from '@lucide/svelte/icons/trash-2';

	const id = $derived(page.params.id ?? '');
	const circle = $derived(store.circle(id));
	const members = $derived(
		(circle?.cameras ?? []).map((c) => store.camera(c)).filter((c) => c !== undefined)
	);
	const recording = $derived(members.some((c) => c.recording?.mode === 'clip'));

	let controls = $state<CircleControl[]>([]);
	let confirming = $state(false);

	// Only the newest answer counts, so switching circles never shows another circle's controls.
	let sequence = 0;
	async function load(circleId: string) {
		const mine = ++sequence;
		const data = await api.circleControls(circleId).catch(() => null);
		if (mine === sequence) controls = data?.controls ?? [];
	}

	// Re-runs when the circle or its members change, not on every refresh of the store.
	const memberKey = $derived(circle?.cameras.join(',') ?? '');
	$effect(() => {
		if (!id) return;
		const circleId = id;
		const memberIds = new Set(memberKey.split(','));
		load(circleId);
		let timer: ReturnType<typeof setTimeout> | undefined;
		const off = store.on((e) => {
			const camera = typeof e.data.camera === 'string' ? e.data.camera : '';
			if (!['camera.control', 'camera.controls'].includes(e.type) || !memberIds.has(camera)) return;
			// One change to the circle sends an event per camera: load once after them.
			clearTimeout(timer);
			timer = setTimeout(() => load(circleId), 300);
		});
		return () => {
			off();
			clearTimeout(timer);
		};
	});

	const groups = $derived(byGroup(controls));

	async function setControl(control: CircleControl, value: unknown) {
		const result = await store.attempt(() => api.setCircleControl(id, control.id, value));
		if (!result) {
			load(id); // show what the cameras really have, not what failed
			return;
		}
		const failed = Object.entries(result.errors);
		if (failed.length) {
			store.toast(
				`Not set on ${failed.map(([c, e]) => `${store.camera(c)?.name ?? c} (${e})`).join(', ')}`,
				'error',
				8000
			);
		} else if (control.kind === 'button') {
			store.toast(
				`${control.label} triggered on ${members.length} ${members.length === 1 ? 'camera' : 'cameras'}`,
				'success'
			);
		}
		load(id);
	}

	function toggleRecord() {
		if (recording) store.attempt(() => api.stopCircle(id));
		else
			store.attempt(async () => {
				const result = await api.recordCircle(id);
				const failed = Object.keys(result.errors).length;
				const n = result.clips.length;
				const cams = (k: number) => `${k} ${k === 1 ? 'camera' : 'cameras'}`;
				store.toast(
					failed ? `Recording ${cams(n)}; ${cams(failed)} failed` : `Recording ${cams(n)}`,
					failed ? 'error' : 'success'
				);
			});
	}

	async function remove() {
		const name = circle?.name;
		const ok = await store.attempt(async () => {
			await api.deleteCircle(id);
			return true;
		});
		if (!ok) return;
		await goto('/'); // first, so the page doesn't flash "not found"
		store.refresh();
		store.toast(`${name} removed`, 'success');
	}
</script>

<svelte:head><title>{circle?.name ?? 'Circle'} · Norn</title></svelte:head>

{#if !store.loaded}
	<div class="aspect-video animate-pulse rounded-2xl bg-surface-2"></div>
{:else if !circle}
	<div class="mx-auto mt-10 max-w-md card p-10 text-center">
		<h1 class="text-lg font-semibold">Circle not found</h1>
		<p class="mt-2 text-sm text-muted">There is no circle “{id}”.</p>
		<a href="/" class="mt-6 btn-ghost">Back to Live</a>
	</div>
{:else}
	<div class="mb-5 flex items-center gap-3">
		<a href="/?circle={circle.id}" class="-ml-2 icon-btn" aria-label="Back"
			><ArrowLeft class="size-5" /></a
		>
		<div class="min-w-0 flex-1">
			<h1 class="truncate text-xl font-semibold tracking-tight">{circle.name}</h1>
			<p class="text-xs text-muted">
				Circle · {members.length}
				{members.length === 1 ? 'camera' : 'cameras'}
			</p>
		</div>
		{#if store.info?.recording_available && members.length}
			<button
				class="btn {recording
					? 'bg-danger text-white'
					: 'bg-danger/12 text-danger hover:bg-danger/20'}"
				onclick={toggleRecord}
				title="One trigger for every camera here. Webhook: POST /api/circles/{circle.id}/record"
			>
				{#if recording}
					<Square class="size-3.5 fill-current" />Stop all
				{:else}
					<CircleDot class="size-4" />Record all
				{/if}
			</button>
		{/if}
	</div>

	<!-- The cameras first; the settings fold up below them. -->
	<div class="grid gap-4 sm:grid-cols-2">
		{#each members as camera (camera.id)}
			<CameraTile {camera} />
		{:else}
			<p class="card px-4 py-6 text-center text-sm text-muted sm:col-span-2">
				No cameras in this circle yet.
			</p>
		{/each}
	</div>

	<div class="mt-6 space-y-4">
		{#each groups as [group, items] (group)}
			<Panel title="{group} · all cameras" name="circle:{group}">
				{#snippet summary()}{items.length} shared{/snippet}
				<div class="-mt-1 divide-y divide-line">
					{#each items as control (control.id)}
						<div class="py-2">
							<ControlField
								{control}
								mixed={control.mixed}
								onchange={(v) => setControl(control, v)}
							/>
							{#if control.mixed}
								<p class="mt-1 pl-12 text-xs text-warning">The cameras differ here.</p>
							{/if}
						</div>
					{/each}
				</div>
			</Panel>
		{/each}

		<Panel title="Circle settings" name="circle-settings">
			{#snippet summary()}Cameras, recording & triggers{/snippet}
			<p class="mb-4 text-xs text-muted">
				Record all from elsewhere: <code class="font-mono"
					>POST /api/circles/{circle.id}/record</code
				>
			</p>
			{#key circle.id}
				<CircleForm {circle} onsaved={() => store.toast('Saved', 'success')} />
			{/key}
			<div class="mt-6 flex items-center justify-between gap-3 border-t border-line pt-4">
				<span class="text-xs text-muted">The cameras stay; only the circle goes.</span>
				{#if confirming}
					<span class="flex gap-2">
						<button class="btn-ghost h-9" onclick={() => (confirming = false)}>Keep</button>
						<button class="btn h-9 bg-danger text-white" onclick={remove}>Remove</button>
					</span>
				{:else}
					<button class="btn-danger h-9" onclick={() => (confirming = true)}
						><Trash2 class="size-4" />Remove</button
					>
				{/if}
			</div>
		</Panel>
	</div>
{/if}
