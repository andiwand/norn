<script lang="ts">
	import { urls, type Recording } from '../api';
	import { deleteRecording } from '../recordings.svelte';
	import { formatBytes, formatDay, formatDuration, formatTime, triggerLabel } from '../format';
	import { store } from '../state.svelte';
	import Download from '@lucide/svelte/icons/download';
	import Trash2 from '@lucide/svelte/icons/trash-2';
	import Pin from '@lucide/svelte/icons/pin';
	import PinOff from '@lucide/svelte/icons/pin-off';
	import X from '@lucide/svelte/icons/x';
	import ChevronLeft from '@lucide/svelte/icons/chevron-left';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';

	let {
		recording = $bindable(null),
		at = 0,
		list,
		ondeleted,
		onchanged
	}: {
		recording: Recording | null;
		/** Where to start playing, in seconds from the start of the video. */
		at?: number;
		/** The recordings this one belongs to (an event's clips, in order): previous and next
		 * buttons, and each video plays on into the next one. */
		list?: Recording[];
		ondeleted?: (r: Recording) => void;
		/** It was pinned or unpinned: the new state. */
		onchanged?: (r: Recording) => void;
	} = $props();

	async function pin() {
		if (!recording) return;
		const wanted = !recording.pinned;
		const updated = await store.pin(recording, wanted);
		if (updated) {
			recording = updated;
			onchanged?.(updated);
		}
	}

	// `at` is for the recording it opens with, not for the next ones in the list.
	let startAt = 0;
	function seek(video: HTMLVideoElement) {
		if (startAt > 0) video.currentTime = startAt;
		startAt = 0;
	}

	let dialog: HTMLDialogElement;
	let confirming = $state(false);

	$effect(() => {
		if (recording && !dialog.open) {
			startAt = at;
			dialog.showModal();
		}
		if (!recording && dialog.open) dialog.close();
		confirming = false;
	});

	const index = $derived(recording && list ? list.findIndex((r) => r.id === recording?.id) : -1);
	const previous = $derived(index > 0 ? list?.[index - 1] : undefined);
	const next = $derived(index >= 0 ? list?.[index + 1] : undefined);
	function go(r: Recording | undefined) {
		if (r) recording = r;
	}

	async function remove() {
		if (!recording) return;
		const r = recording;
		if (!(await deleteRecording(r))) return;
		recording = null;
		ondeleted?.(r);
	}
</script>

<dialog
	bind:this={dialog}
	onclose={() => (recording = null)}
	onclick={(e) => e.target === dialog && dialog.close()}
	class="m-auto w-[min(100vw-2rem,64rem)] max-w-none rounded-2xl border border-line bg-surface p-0 text-text shadow-2xl backdrop:bg-black/70 backdrop:backdrop-blur-sm"
>
	{#if recording}
		<div class="flex items-center justify-between gap-4 px-5 py-3">
			<div class="min-w-0">
				<div class="truncate font-semibold">
					{store.camera(recording.camera)?.name ?? recording.camera}
				</div>
				<div class="text-xs text-muted">
					{formatDay(recording.day)} · {formatTime(recording.start)} · {triggerLabel(
						recording.trigger
					)}
					{#if recording.duration}· {formatDuration(recording.duration)}{/if} · {formatBytes(
						recording.size
					)}
				</div>
			</div>
			<div class="flex shrink-0 items-center gap-1">
				{#if list && index >= 0 && list.length > 1}
					<button
						class="icon-btn"
						onclick={() => go(previous)}
						disabled={!previous}
						aria-label="Previous clip"
						title="Previous clip"><ChevronLeft class="size-5" /></button
					>
					<span class="min-w-14 text-center text-xs text-muted tabular-nums" aria-live="polite"
						>{index + 1} of {list.length}</span
					>
					<button
						class="icon-btn"
						onclick={() => go(next)}
						disabled={!next}
						aria-label="Next clip"
						title="Next clip"><ChevronRight class="size-5" /></button
					>
				{/if}
				<button class="icon-btn" onclick={() => dialog.close()} aria-label="Close"
					><X class="size-5" /></button
				>
			</div>
		</div>
		{#if recording.kind === 'picture'}
			<img
				src={urls.recording(recording)}
				alt="{store.camera(recording.camera)?.name ?? recording.camera}, {formatTime(
					recording.start
				)}"
				class="aspect-video w-full bg-black object-contain"
			/>
		{:else}
			<!-- svelte-ignore a11y_media_has_caption -->
			<video
				src={urls.recording(recording)}
				controls
				autoplay
				playsinline
				onloadedmetadata={(e) => seek(e.currentTarget)}
				onended={() => go(next)}
				class="aspect-video w-full bg-black"
			></video>
		{/if}
		<div class="flex flex-wrap items-center justify-end gap-2 px-5 py-3">
			{#if confirming}
				<span class="mr-auto text-sm text-muted">Delete this {recording.kind} for good?</span>
				<button class="btn-ghost" onclick={() => (confirming = false)}>Keep</button>
				<button class="btn bg-danger text-white" onclick={remove}>Delete</button>
			{:else}
				<span class="mr-auto text-xs text-muted">
					{#if recording.live}
						Still being recorded.
					{:else if recording.pinned}
						Pinned: kept until you unpin it.
					{:else if recording.expires}
						Norn deletes it on {new Date(recording.expires).toLocaleDateString([], {
							month: 'short',
							day: 'numeric'
						})}.
					{:else}
						Kept until you delete it.
					{/if}
				</span>
				{#if !recording.live}
					<button class="btn-ghost" onclick={pin}
						>{#if recording.pinned}<PinOff class="size-4" />Unpin{:else}<Pin
								class="size-4"
							/>Pin{/if}</button
					>
					<button class="btn-danger" onclick={() => (confirming = true)}
						><Trash2 class="size-4" />Delete</button
					>
				{/if}
				<a class="btn-ghost" href={urls.recording(recording)} download
					><Download class="size-4" />Download</a
				>
			{/if}
		</div>
	{/if}
</dialog>
