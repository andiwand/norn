<script lang="ts">
	import { urls, type Recording } from '../api';
	import { formatDuration, formatTime, triggerLabel } from '../format';
	import Film from '@lucide/svelte/icons/film';
	import Play from '@lucide/svelte/icons/play';

	let {
		recording,
		cameraName,
		onopen
	}: { recording: Recording; cameraName?: string; onopen: (r: Recording) => void } = $props();
</script>

<button
	class="group block w-full overflow-hidden rounded-2xl border border-line bg-surface text-left transition hover:border-line-strong hover:shadow-xl"
	onclick={() => onopen(recording)}
>
	<div class="relative aspect-video bg-surface-2">
		{#if recording.thumbnail}
			<img
				src={urls.thumbnail(recording)}
				alt=""
				loading="lazy"
				class="h-full w-full object-cover"
			/>
		{:else}
			<div class="grid h-full place-items-center text-muted/60"><Film class="size-7" /></div>
		{/if}
		<div
			class="absolute inset-0 grid place-items-center opacity-0 transition group-hover:opacity-100"
		>
			<span class="glass-btn size-12"><Play class="size-5 translate-x-px fill-current" /></span>
		</div>
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
			class="shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium {recording.trigger ===
			'continuous'
				? 'bg-surface-3 text-muted'
				: 'bg-accent/15 text-accent'}"
		>
			{triggerLabel(recording.trigger)}
		</span>
	</div>
</button>
