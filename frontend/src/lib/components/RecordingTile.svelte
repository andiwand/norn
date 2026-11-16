<script lang="ts">
	import { urls, type Recording } from '../api';
	import { formatDuration, formatTime, triggerLabel } from '../format';
	import Film from '@lucide/svelte/icons/film';
	import Play from '@lucide/svelte/icons/play';
	import Trash2 from '@lucide/svelte/icons/trash-2';
	import Pin from '@lucide/svelte/icons/pin';
	import PinOff from '@lucide/svelte/icons/pin-off';
	import Download from '@lucide/svelte/icons/download';
	import LifetimeRing from './LifetimeRing.svelte';

	let {
		recording,
		cameraName,
		onopen,
		ondelete,
		onpin,
		now
	}: {
		recording: Recording;
		cameraName?: string;
		onopen: (r: Recording) => void;
		ondelete?: (r: Recording) => void;
		/** Pin or unpin; without it the tile has no pin button. */
		onpin?: (r: Recording, pinned: boolean) => void;
		/** The time the lifetime rings count from; the page ticks it. */
		now?: number;
	} = $props();

	// Deleting takes two clicks: the first arms the button, the second deletes.
	let armed = $state(false);
	let disarm: ReturnType<typeof setTimeout> | undefined;

	function clickDelete() {
		if (!armed) {
			armed = true;
			clearTimeout(disarm);
			disarm = setTimeout(() => (armed = false), 3000);
			return;
		}
		clearTimeout(disarm);
		armed = false;
		ondelete?.(recording);
	}
</script>

<div
	class="group relative overflow-hidden rounded-2xl border border-line bg-surface transition hover:border-line-strong hover:shadow-xl"
>
	<button class="block w-full text-left" onclick={() => onopen(recording)}>
		<div class="relative aspect-video bg-surface-2">
			{#if recording.thumbnail}
				<img src={urls.small(recording)} alt="" loading="lazy" class="h-full w-full object-cover" />
			{:else}
				<div class="grid h-full place-items-center text-muted/60"><Film class="size-7" /></div>
			{/if}
			{#if recording.kind === 'video'}
				<div
					class="absolute inset-0 grid place-items-center opacity-0 transition group-hover:opacity-100"
				>
					<span class="glass-btn size-12"><Play class="size-5 translate-x-px fill-current" /></span>
				</div>
			{/if}
			{#if recording.duration}
				<span
					class="absolute right-2 bottom-2 rounded-md bg-black/65 px-1.5 py-0.5 text-[11px] font-medium text-white tabular-nums"
				>
					{formatDuration(recording.duration)}
				</span>
			{/if}
		</div>
		<div class="flex items-center justify-between gap-2 px-3 py-2.5">
			<div class="min-w-0">
				<div class="truncate text-sm font-medium">{cameraName ?? recording.camera}</div>
				<div class="text-xs text-muted tabular-nums">{formatTime(recording.start)}</div>
			</div>
			<span
				class="shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium {[
					'continuous',
					'interval'
				].includes(recording.trigger)
					? 'bg-surface-3 text-muted'
					: 'bg-accent/15 text-accent'}"
			>
				{triggerLabel(recording.trigger)}
			</span>
		</div>
	</button>
	{#if recording.live}
		<span
			class="absolute top-2 right-2 flex items-center gap-1.5 rounded-full bg-black/55 px-2 py-1 text-[11px] font-medium text-white backdrop-blur-md"
			><span class="size-1.5 animate-pulse rounded-full bg-danger"></span>Recording</span
		>
	{/if}
	{#if recording.pinned}
		<span
			class="absolute top-2 left-2 grid size-7 place-items-center rounded-full bg-accent text-accent-ink"
			title="Pinned: kept until you unpin it"><Pin class="size-3.5" /></span
		>
	{:else if recording.expires}
		<LifetimeRing
			start={recording.start}
			expires={recording.expires}
			{now}
			class="pointer-events-auto absolute top-2 left-2"
		/>
	{/if}
	{#if !recording.live}
		<!-- Small actions, shown on hover (always on touch screens). -->
		<div
			class="absolute top-2 right-2 flex items-center gap-1 transition focus-within:opacity-100 {armed
				? 'opacity-100'
				: '[@media(hover:hover)]:opacity-0 [@media(hover:hover)]:group-hover:opacity-100'}"
		>
			{#if onpin && !armed}
				<button
					class="tile-action"
					onclick={() => onpin(recording, !recording.pinned)}
					aria-label={recording.pinned ? 'Unpin' : 'Pin: keep it'}
					title={recording.pinned ? 'Unpin' : 'Pin: Norn keeps it'}
				>
					{#if recording.pinned}<PinOff class="size-4" />{:else}<Pin class="size-4" />{/if}
				</button>
			{/if}
			{#if !armed}
				<a
					class="tile-action"
					href={urls.recording(recording)}
					download
					aria-label="Download"
					title="Download"><Download class="size-4" /></a
				>
			{/if}
			{#if ondelete}
				<button
					class="tile-action {armed ? 'w-auto bg-danger px-2' : 'hover:bg-danger'}"
					onclick={clickDelete}
					onmouseleave={() => {
						clearTimeout(disarm);
						disarm = setTimeout(() => (armed = false), 800);
					}}
					aria-label={armed ? 'Click again to delete' : 'Delete recording'}
					title={armed ? 'Click again to delete' : 'Delete'}
				>
					<Trash2 class="size-4" />
					{#if armed}<span class="pr-0.5 text-xs font-medium">Delete?</span>{/if}
				</button>
			{/if}
		</div>
	{/if}
</div>
