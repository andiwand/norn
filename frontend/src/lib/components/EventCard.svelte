<script lang="ts">
	// One event: a clip, or a burst of clips of one camera close together. Play goes through
	// them in order; Keep pins them all; Delete removes the ones not pinned, after a confirmation.
	import { tick } from 'svelte';
	import { api, urls, type Recording } from '../api';
	import { store } from '../state.svelte';
	import { formatTime, triggerLabel, unconfirmed } from '../format';
	import { videoLength, type ClipEvent } from '../events';
	import TriggerIcon from './TriggerIcon.svelte';
	import Film from '@lucide/svelte/icons/film';
	import Play from '@lucide/svelte/icons/play';
	import Pin from '@lucide/svelte/icons/pin';
	import PinOff from '@lucide/svelte/icons/pin-off';
	import Trash2 from '@lucide/svelte/icons/trash-2';
	import SlidersHorizontal from '@lucide/svelte/icons/sliders-horizontal';

	let {
		event,
		cameraName,
		highlight = false,
		onplay,
		onchanged,
		ondeleted
	}: {
		event: ClipEvent;
		cameraName: string;
		/** Draw attention to it (the heat map jumped here). */
		highlight?: boolean;
		/** Open a clip, with the event's clips to go on through. */
		onplay: (clip: Recording, clips: Recording[]) => void;
		/** Clips were pinned or unpinned: their new state. */
		onchanged: (updated: Recording[]) => void;
		ondeleted: (ids: string[]) => void;
	} = $props();

	// Triggers Norn or the camera detect, as opposed to a person pressing record.
	const BY_HAND = new Set(['manual', 'webhook']);
	const SHOWN = 24; // thumbnails before "+ n more"

	const count = $derived(event.clips.length);
	const single = $derived(count === 1);
	const first = $derived(event.clips[0]);
	const allPinned = $derived(event.pinned === count);
	const deletable = $derived(event.clips.filter((c) => !c.pinned));
	const detected = $derived(event.triggers.some(([t]) => !BY_HAND.has(t)));
	const main = $derived(event.triggers[0][0]);
	// The camera's alarms in it that Norn's AI looked at and didn't see.
	const doubtful = $derived(event.clips.filter(unconfirmed).length);
	const title = $derived(event.triggers.map(([t]) => triggerLabel(t)).join(', '));
	const range = $derived(
		single
			? formatTime(first.start)
			: `${formatTime(first.start)} – ${formatTime(new Date(event.end).toISOString())}`
	);
	const expiry = $derived.by(() => {
		if (allPinned) return single ? 'Pinned: kept until you unpin it' : 'All pinned: kept';
		const soonest = deletable
			.map((c) => c.expires)
			.filter((e): e is string => !!e)
			.sort()[0];
		if (!soonest) return 'Kept until you delete it';
		const date = new Date(soonest).toLocaleDateString([], { month: 'short', day: 'numeric' });
		return `${single ? 'Norn deletes it' : 'Norn deletes them'} from ${date}`;
	});

	// The colour of what started it: people warm, animals and vehicles cool, the rest the accent.
	const color = $derived(
		main === 'person' || main === 'face'
			? 'text-warning'
			: main === 'animal' || main === 'vehicle'
				? 'text-accent-2'
				: 'text-accent'
	);
	const tile = $derived(
		main === 'person' || main === 'face'
			? 'bg-warning/15'
			: main === 'animal' || main === 'vehicle'
				? 'bg-accent-2/15'
				: 'bg-accent/15'
	);

	let expanded = $state(false);
	let confirming = $state(false);
	let busy = $state(false);
	const shown = $derived(expanded ? event.clips : event.clips.slice(0, SHOWN));

	async function keep(pinned: boolean) {
		busy = true;
		const todo = event.clips.filter((c) => c.pinned !== pinned);
		const results = await Promise.allSettled(todo.map((c) => api.pinRecording(c.id, pinned)));
		busy = false;
		const done = results.flatMap((r) => (r.status === 'fulfilled' ? [r.value] : []));
		if (done.length) onchanged(done);
		const failed = todo.length - done.length;
		if (failed) store.toast(`${failed} of ${todo.length} couldn't be changed`, 'error');
		else
			store.toast(
				pinned
					? `Pinned ${plural(done.length, 'clip')}: Norn keeps them`
					: `Unpinned ${plural(done.length, 'clip')}`,
				'success'
			);
	}

	async function remove() {
		busy = true;
		const todo = deletable;
		const results = await Promise.allSettled(todo.map((c) => api.deleteRecording(c.id)));
		busy = false;
		confirming = false;
		const gone = todo.filter((_, i) => results[i].status === 'fulfilled').map((c) => c.id);
		if (gone.length) ondeleted(gone);
		const failed = todo.length - gone.length;
		if (failed) store.toast(`${failed} of ${todo.length} couldn't be deleted`, 'error');
		else store.toast(`Deleted ${plural(gone.length, 'clip')}`, 'success');
	}

	// The confirmation takes the focus (on Cancel: Enter doesn't delete by accident); Escape
	// cancels it.
	function focus(node: HTMLElement) {
		node.focus();
	}
	// Back on the Delete button that asked, so the keyboard stays where it was.
	let askButton = $state<HTMLButtonElement | null>(null);
	async function cancel() {
		confirming = false;
		await tick();
		askButton?.focus();
	}
	const escape = (e: KeyboardEvent) => {
		if (e.key === 'Escape') cancel();
	};

	function plural(n: number, word: string) {
		return `${n} ${word}${n === 1 ? '' : 's'}`;
	}
</script>

<article
	id="event-{event.id}"
	class="min-w-0 scroll-mt-24 overflow-hidden card transition-shadow duration-500 {highlight
		? 'ring-2 ring-accent'
		: ''}"
	aria-label="{title}, {cameraName}, {range}"
>
	<div class="flex items-start gap-3 p-3 sm:items-center sm:px-4">
		{#if single}
			<!-- One clip: its picture is the play button. -->
			<button
				class="group relative aspect-video w-28 shrink-0 overflow-hidden rounded-lg bg-surface-2 sm:w-40"
				onclick={() => onplay(first, event.clips)}
				aria-label="Play the clip"
			>
				{#if first.thumbnail}
					<img src={urls.small(first)} alt="" loading="lazy" class="size-full object-cover" />
				{:else}
					<Film class="m-auto size-6 text-muted/60" />
				{/if}
				<span
					class="absolute inset-0 grid place-items-center bg-black/25 opacity-100 transition sm:opacity-0 sm:group-hover:opacity-100 sm:group-focus-visible:opacity-100"
					><span class="glass-btn size-9"><Play class="size-4 translate-x-px fill-current" /></span
					></span
				>
			</button>
		{:else}
			<span class="grid size-10 shrink-0 place-items-center rounded-xl {tile} {color}">
				<TriggerIcon trigger={main} class="size-5" />
			</span>
		{/if}
		<div class="min-w-0 flex-1">
			<h3 class="flex min-w-0 items-center gap-1.5 font-semibold">
				{#if single}<span class="shrink-0 {color}"
						><TriggerIcon trigger={main} class="size-4" /></span
					>{/if}
				<span class="truncate">{title} · {cameraName}</span>
			</h3>
			<p class="mt-0.5 text-xs text-muted tabular-nums">
				{range} · {single
					? videoLength(event.seconds)
					: `${count} clips · ${videoLength(event.seconds)}`}
			</p>
			{#if doubtful}
				<p
					class="mt-0.5 text-xs font-medium text-warning"
					title="The camera reported it; Norn's AI looked at the same time and saw nothing: probably false alarms"
				>
					{doubtful === event.clips.length
						? single
							? "Only the camera saw it: Norn's AI saw nothing"
							: `Only the camera saw these: Norn's AI saw nothing`
						: `${doubtful} of ${event.clips.length} only the camera saw`}
				</p>
			{/if}
			<p class="mt-0.5 flex items-center gap-1 text-xs text-muted">
				{#if event.pinned}<Pin class="size-3" />{/if}{expiry}{#if event.pinned && !allPinned}
					· {event.pinned} pinned{/if}
			</p>
		</div>
		{#if !single}
			<button
				class="btn-primary hidden h-9 sm:inline-flex"
				onclick={() => onplay(first, event.clips)}
				><Play class="size-4 fill-current" />Play all</button
			>
		{/if}
	</div>

	{#if !single}
		<!-- The clips in order; each opens at itself and plays on. -->
		<ul class="flex [scrollbar-width:thin] gap-2 overflow-x-auto px-3 pb-3 sm:px-4" role="list">
			{#each shown as clip, i (clip.id)}
				<li class="shrink-0">
					<button
						class="group relative block aspect-video w-32 overflow-hidden rounded-lg bg-surface-2 sm:w-40"
						onclick={() => onplay(clip, event.clips)}
						aria-label="Play clip {i + 1} of {count}, {formatTime(clip.start)}"
					>
						{#if clip.thumbnail}
							<img src={urls.small(clip)} alt="" loading="lazy" class="size-full object-cover" />
						{:else}
							<Film class="m-auto size-6 text-muted/60" />
						{/if}
						<span
							class="absolute bottom-1 left-1 rounded bg-black/60 px-1.5 py-0.5 text-[10px] font-medium text-white tabular-nums"
							>{formatTime(clip.start)}</span
						>
						{#if clip.pinned}
							<span class="absolute top-1 right-1 rounded bg-black/60 p-0.5 text-white"
								><Pin class="size-3" /></span
							>
						{/if}
						<span
							class="absolute inset-0 grid place-items-center opacity-0 transition group-hover:opacity-100 group-focus-visible:opacity-100"
							><span class="glass-btn size-9"
								><Play class="size-4 translate-x-px fill-current" /></span
							></span
						>
					</button>
				</li>
			{/each}
			{#if count > shown.length}
				<li class="shrink-0">
					<button
						class="grid aspect-video w-32 place-items-center rounded-lg border border-dashed border-line-strong text-sm font-medium text-muted hover:text-text sm:w-40"
						onclick={() => (expanded = true)}>+ {count - shown.length} more</button
					>
				</li>
			{/if}
		</ul>
	{/if}

	<div
		class="flex min-h-14 flex-wrap items-center gap-2 border-t border-line px-3 py-2.5 sm:px-4"
		aria-busy={busy}
	>
		{#if confirming}
			<p class="mr-auto text-sm" role="alert">
				Delete {deletable.length === 1 ? 'this clip' : `these ${deletable.length} clips`} for good?
				<span class="text-muted"
					>This can't be undone.{#if event.pinned}
						{event.pinned} pinned {event.pinned === 1 ? 'clip stays' : 'clips stay'}.{/if}</span
				>
			</p>
			<button class="btn-ghost h-9" onclick={cancel} onkeydown={escape} disabled={busy} use:focus
				>Cancel</button
			>
			<button
				class="btn h-9 bg-danger text-white"
				onclick={remove}
				onkeydown={escape}
				disabled={busy}
				><Trash2 class="size-4" />Delete {deletable.length === 1 ? '' : deletable.length}</button
			>
		{:else}
			{#if !single}
				<button class="btn-primary h-9 sm:hidden" onclick={() => onplay(first, event.clips)}
					><Play class="size-4 fill-current" />Play all</button
				>
			{/if}
			<button
				class="btn-ghost h-9"
				onclick={() => keep(!allPinned)}
				disabled={busy}
				title={allPinned
					? 'Let Norn delete them again when they get old'
					: 'Pin: Norn keeps them, whatever the limits'}
				>{#if allPinned}<PinOff class="size-4" />Unpin{:else}<Pin class="size-4" />Keep{/if}</button
			>
			{#if deletable.length}
				<button
					class="btn-ghost h-9 text-danger"
					bind:this={askButton}
					onclick={() => (confirming = true)}
					disabled={busy}
					><Trash2 class="size-4" />Delete{single || deletable.length === 1
						? ''
						: ` ${deletable.length}`}</button
				>
			{/if}
			{#if detected}
				<a
					href="/cameras/{event.camera}?tab=recording"
					class="ml-auto flex h-9 min-w-9 items-center justify-center gap-1.5 rounded-xl px-2 text-sm font-medium text-accent hover:bg-accent/10"
					title="False alarms? Change what records on this camera, and how sure the detection must be"
					><SlidersHorizontal class="size-4" /><span class="sr-only sm:not-sr-only"
						>Tune detection</span
					></a
				>
			{/if}
		{/if}
	</div>
</article>
