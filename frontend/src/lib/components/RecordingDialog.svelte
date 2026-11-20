<script lang="ts">
	import { urls, type ClipObjects, type Recording } from '../api';
	import ObjectBoxes from './ObjectBoxes.svelte';
	import ScanEye from '@lucide/svelte/icons/scan-eye';
	import { deleteRecording } from '../recordings.svelte';
	import {
		clipSources,
		formatBytes,
		formatDay,
		formatDuration,
		formatTime,
		triggerLabel,
		unconfirmed,
		aKind
	} from '../format';
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

	// What Norn's AI found during the clip, drawn over the video as it plays (not burnt into it).
	let seen = $state<ClipObjects>([]);
	let showBoxes = $state(true);
	let time = $state(0);
	let size = $state<[number, number]>([16, 9]);
	$effect(() => {
		const r = recording;
		seen = [];
		if (!r || r.kind !== 'video' || r.live) return;
		let gone = false;
		fetch(urls.objects(r))
			.then((response) => (response.ok ? response.json() : []))
			.then((data: ClipObjects) => {
				if (!gone && Array.isArray(data)) seen = data;
			})
			.catch(() => {});
		return () => {
			gone = true;
		};
	});
	// The newest still at the playhead; none when it is older than a few stills' gap.
	const boxes = $derived.by(() => {
		let last: ClipObjects[number] | undefined;
		for (const s of seen) {
			if (s.at > time) break;
			last = s;
		}
		return last && time - last.at < 8 ? last.objects : [];
	});
	// Where the picture is in the 16:9 player: the boxes are fractions of the picture.
	const frame = $derived.by(() => {
		const ratio = size[0] / size[1] / (16 / 9);
		return ratio >= 1
			? `left:0;width:100%;top:${(100 - 100 / ratio) / 2}%;height:${100 / ratio}%`
			: `top:0;height:100%;left:${(100 - 100 * ratio) / 2}%;width:${100 * ratio}%`;
	});

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
					)}{#if clipSources(recording)}{` (${clipSources(recording)})`}{/if}
					{#if recording.duration}· {formatDuration(recording.duration)}{/if} · {formatBytes(
						recording.size
					)}
				</div>
				{#if unconfirmed(recording)}
					<div class="mt-0.5 text-xs font-medium text-warning">
						The camera reported {aKind(recording.trigger)}; Norn's AI looked and saw nothing:
						probably a false alarm.
					</div>
				{/if}
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
			<div class="relative aspect-video w-full bg-black">
				<!-- svelte-ignore a11y_media_has_caption -->
				<video
					src={urls.recording(recording)}
					controls
					autoplay
					playsinline
					onloadedmetadata={(e) => {
						const v = e.currentTarget;
						if (v.videoWidth && v.videoHeight) size = [v.videoWidth, v.videoHeight];
						seek(v);
					}}
					ontimeupdate={(e) => (time = e.currentTarget.currentTime)}
					onseeked={(e) => (time = e.currentTarget.currentTime)}
					onended={() => go(next)}
					class="absolute inset-0 h-full w-full"
				></video>
				{#if showBoxes && boxes.length}
					<div class="pointer-events-none absolute" style={frame}>
						<ObjectBoxes objects={boxes} />
					</div>
				{/if}
			</div>
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
				{#if seen.some((s) => s.objects.length)}
					<button
						class="btn-ghost {showBoxes ? 'text-accent' : ''}"
						aria-pressed={showBoxes}
						title="Boxes around what Norn's AI found, with how sure it was"
						onclick={() => (showBoxes = !showBoxes)}><ScanEye class="size-4" />Boxes</button
					>
				{/if}
				{#if !recording.live}
					<button class="btn-ghost" onclick={pin}
						>{#if recording.pinned}<PinOff class="size-4" />Unpin{:else}<Pin
								class="size-4"
							/>Pin{/if}</button
					>
					{#if store.isAdmin}
						<button class="btn-danger" onclick={() => (confirming = true)}
							><Trash2 class="size-4" />Delete</button
						>
					{/if}
				{/if}
				<a class="btn-ghost" href={urls.recording(recording)} download
					><Download class="size-4" />Download</a
				>
			{/if}
		</div>
	{/if}
</dialog>
