<script lang="ts">
	// Norn's log, newest at the bottom, updating while it is open. Credentials are scrubbed on
	// the server before any line is kept.
	import { api, type LogLine } from '../api';
	import Download from '@lucide/svelte/icons/download';

	let level = $state('INFO');
	let text = $state('');
	let lines = $state<LogLine[]>([]);
	let file = $state<string | null>(null);
	let box = $state<HTMLElement>();
	let follow = $state(true); // keep the newest in view, unless someone scrolled up

	$effect(() => {
		const query = { level, text: text.trim() };
		let after = 0;
		let stopped = false;
		let busy = false; // one request at a time: overlapping ones would add the same lines
		lines = [];
		const load = async () => {
			if (busy) return;
			busy = true;
			const data = await api.logs({ ...query, after, limit: 500 }).catch(() => null);
			busy = false;
			if (stopped || !data) return;
			file = data.file;
			const fresh = data.lines.filter((l) => l.id > after);
			if (fresh.length) {
				after = fresh[fresh.length - 1].id;
				lines = [...lines, ...fresh].slice(-1000);
			}
		};
		load();
		const timer = setInterval(() => {
			if (!document.hidden) load();
		}, 3000);
		return () => {
			stopped = true;
			clearInterval(timer);
		};
	});

	$effect(() => {
		void lines.length;
		if (follow && box) queueMicrotask(() => box && (box.scrollTop = box.scrollHeight));
	});

	const colors: Record<string, string> = {
		DEBUG: 'text-muted',
		INFO: 'text-text',
		WARNING: 'text-warning',
		ERROR: 'text-danger',
		CRITICAL: 'text-danger'
	};
	const time = (t: number) =>
		new Date(t * 1000).toLocaleTimeString([], {
			hour: '2-digit',
			minute: '2-digit',
			second: '2-digit'
		});
</script>

<div class="mb-3 flex flex-wrap items-center gap-2">
	<select class="input h-9 w-auto pr-8 text-xs" bind:value={level} aria-label="Level">
		<option value="DEBUG">Everything</option>
		<option value="INFO">Info and up</option>
		<option value="WARNING">Warnings and errors</option>
		<option value="ERROR">Errors</option>
	</select>
	<input class="input h-9 min-w-0 flex-1 basis-40 text-xs" placeholder="Search" bind:value={text} />
	{#if file}
		<a class="btn-ghost h-9 text-xs" href="/api/logs/file" download title={file}
			><Download class="size-4" />Log file</a
		>
	{/if}
</div>
<div
	bind:this={box}
	class="h-80 overflow-auto rounded-xl bg-surface-2 p-3 font-mono text-[11px] leading-relaxed"
	onscroll={() => box && (follow = box.scrollHeight - box.scrollTop - box.clientHeight < 40)}
>
	{#each lines as line (line.id)}
		<div class="break-words whitespace-pre-wrap {colors[line.level]}">
			<span class="text-muted">{time(line.time)}</span>
			{line.level === 'INFO' ? '' : `${line.level} `}<span class="text-muted">{line.logger}</span>
			{line.message}
		</div>
	{:else}
		<p class="text-muted">Nothing yet.</p>
	{/each}
</div>
