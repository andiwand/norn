<script lang="ts">
	import { api, urls, type Recording } from '../api';
	import { formatBytes, formatDay, formatDuration, formatTime, triggerLabel } from '../format';
	import { store } from '../state.svelte';
	import Download from '@lucide/svelte/icons/download';
	import Trash2 from '@lucide/svelte/icons/trash-2';
	import X from '@lucide/svelte/icons/x';

	let {
		recording = $bindable(null),
		at = 0,
		ondeleted
	}: {
		recording: Recording | null;
		/** Where to start playing, in seconds from the start of the video. */
		at?: number;
		ondeleted?: (r: Recording) => void;
	} = $props();

	function seek(video: HTMLVideoElement) {
		if (at > 0) video.currentTime = at;
	}

	let dialog: HTMLDialogElement;
	let confirming = $state(false);

	$effect(() => {
		if (recording && !dialog.open) dialog.showModal();
		if (!recording && dialog.open) dialog.close();
		confirming = false;
	});

	async function remove() {
		if (!recording) return;
		const r = recording;
		try {
			await api.deleteRecording(r.id);
			store.toast('Recording deleted', 'success');
			recording = null;
			ondeleted?.(r);
		} catch (e) {
			store.toast(e instanceof Error ? e.message : String(e), 'error');
		}
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
			<button class="icon-btn" onclick={() => dialog.close()} aria-label="Close"
				><X class="size-5" /></button
			>
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
