<script lang="ts">
	// What Norn keeps in each storage stage: the RAM buffer, the temporary storage, the recordings.
	import { api, type Storage, type StorageStage } from '../api';
	import { formatBytes } from '../format';
	import { store } from '../state.svelte';
	import MemoryStick from '@lucide/svelte/icons/memory-stick';
	import HardDriveDownload from '@lucide/svelte/icons/hard-drive-download';
	import HardDrive from '@lucide/svelte/icons/hard-drive';

	let storage = $state<Storage | null>(null);

	$effect(() => {
		const load = () =>
			api
				.storage()
				.then((s) => (storage = s))
				.catch(() => {});
		load();
		const timer = setInterval(load, 20_000);
		const off = store.on((e) => {
			if (e.type === 'recording.finished' || e.type === 'recording.deleted') load();
		});
		return () => {
			clearInterval(timer);
			off();
		};
	});

	const stages = $derived(
		storage
			? [
					{
						key: 'buffer',
						label: 'Buffer',
						hint: 'The last seconds before a trigger',
						icon: MemoryStick,
						stage: storage.buffer
					},
					{
						key: 'temp',
						label: 'Temporary',
						hint: 'What is being recorded right now',
						icon: HardDriveDownload,
						stage: storage.temp
					},
					{
						key: 'recordings',
						label: 'Recordings',
						hint: 'Finished videos and pictures',
						icon: HardDrive,
						stage: storage.recordings
					}
				]
			: []
	);

	function share(s: StorageStage): number {
		return s.total ? Math.min(100, (s.used / s.total) * 100) : 0;
	}
	function taken(s: StorageStage): number {
		return s.total && s.free !== null ? Math.min(100, ((s.total - s.free) / s.total) * 100) : 0;
	}
</script>

{#if storage}
	<div class="grid gap-3 sm:grid-cols-3">
		{#each stages as { key, label, hint, icon: Icon, stage } (key)}
			<div class="rounded-xl border border-line bg-surface-2/60 p-4" title={stage.path}>
				<div class="flex items-center gap-2 text-muted">
					<Icon class="size-4" /><span class="text-xs font-medium">{label}</span>
					<span
						class="ml-auto rounded-md px-1.5 py-0.5 text-[10px] font-semibold tracking-wide {stage.ram
							? 'bg-accent/15 text-accent'
							: 'bg-surface-3 text-muted'}"
						title={stage.ram ? `In memory (${stage.path})` : `On disk (${stage.path})`}
						>{stage.ram ? 'RAM' : 'Disk'}</span
					>
				</div>
				<div class="mt-2 text-xl font-semibold tabular-nums">{formatBytes(stage.used)}</div>
				{#if stage.total}
					<!-- The disk: the darker part is everything on it, the bright part is Norn. -->
					<div class="mt-2 h-1.5 overflow-hidden rounded-full bg-surface-3">
						<div class="relative h-full bg-line-strong" style:width="{taken(stage)}%">
							<div
								class="absolute inset-y-0 left-0 bg-accent"
								style:width="{taken(stage) ? (share(stage) / taken(stage)) * 100 : 0}%"
							></div>
						</div>
					</div>
					<p class="mt-1.5 text-xs text-muted tabular-nums">
						{stage.free !== null ? `${formatBytes(stage.free)} free of ` : ''}{formatBytes(
							stage.total
						)}
					</p>
				{/if}
				<p class="mt-1 text-xs text-muted">{hint}</p>
			</div>
		{/each}
	</div>
{/if}
