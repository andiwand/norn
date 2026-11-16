<script lang="ts">
	// What Norn costs the machine right now: CPU and memory per process, and the GPU.
	import { api, type Resources } from '../api';
	import { formatBytes } from '../format';
	import { store } from '../state.svelte';

	let resources = $state<Resources | null>(null);

	$effect(() => {
		const load = () =>
			api
				.resources()
				.then((r) => (resources = r))
				.catch(() => {});
		load();
		const timer = setInterval(load, 5000);
		return () => clearInterval(timer);
	});

	const machine = $derived(resources ? resources.cpu / resources.system.cores : 0);
	const memoryShare = $derived(
		resources ? (resources.memory / resources.system.memory_total) * 100 : 0
	);
</script>

{#if resources}
	<div class="grid gap-3 sm:grid-cols-3">
		<div class="rounded-xl border border-line bg-surface-2/60 p-4">
			<div class="text-xs font-medium text-muted">CPU</div>
			<div class="mt-2 text-xl font-semibold tabular-nums">{machine.toFixed(1)} %</div>
			<div class="mt-2 h-1.5 overflow-hidden rounded-full bg-surface-3">
				<div class="h-full bg-accent" style:width="{Math.min(100, machine)}%"></div>
			</div>
			<p class="mt-1.5 text-xs text-muted tabular-nums">
				of {resources.system.cores} cores · machine {resources.system.cpu.toFixed(0)} %
			</p>
		</div>
		<div class="rounded-xl border border-line bg-surface-2/60 p-4">
			<div class="text-xs font-medium text-muted">Memory</div>
			<div class="mt-2 text-xl font-semibold tabular-nums">{formatBytes(resources.memory)}</div>
			<div class="mt-2 h-1.5 overflow-hidden rounded-full bg-surface-3">
				<div class="h-full bg-accent" style:width="{Math.min(100, memoryShare)}%"></div>
			</div>
			<p class="mt-1.5 text-xs text-muted tabular-nums">
				of {formatBytes(resources.system.memory_total)} · {formatBytes(
					resources.system.memory_available
				)} free
			</p>
		</div>
		<div class="rounded-xl border border-line bg-surface-2/60 p-4">
			<div class="text-xs font-medium text-muted">GPU</div>
			<div class="mt-2 text-xl font-semibold">{resources.gpu.used ? 'In use' : 'Not used'}</div>
			<p class="mt-1.5 text-xs text-muted">
				{resources.gpu.available.length
					? `Available: ${resources.gpu.available.join(', ')}. Norn encodes on the CPU for now.`
					: 'Norn copies video without decoding it, so it needs no GPU.'}
			</p>
		</div>
	</div>
	<div class="mt-3 overflow-x-auto">
		<table class="w-full text-sm">
			<thead>
				<tr class="border-b border-line text-left text-xs text-muted">
					<th class="py-2 pr-3 font-medium">Process</th>
					<th class="px-3 py-2 font-medium">Camera</th>
					<th class="px-3 py-2 text-right font-medium">CPU</th>
					<th class="py-2 pl-3 text-right font-medium">Memory</th>
				</tr>
			</thead>
			<tbody class="divide-y divide-line">
				{#each resources.processes as p (p.pid)}
					<tr>
						<td class="py-2 pr-3 font-medium">{p.kind}</td>
						<td class="px-3 py-2 text-muted">
							{p.camera ? (store.camera(p.camera)?.name ?? p.camera) : ''}
						</td>
						<td class="px-3 py-2 text-right tabular-nums">{p.cpu.toFixed(1)} %</td>
						<td class="py-2 pl-3 text-right text-muted tabular-nums">{formatBytes(p.memory)}</td>
					</tr>
				{/each}
			</tbody>
		</table>
		<p class="mt-2 text-xs text-muted">CPU per process: 100 % is one full core.</p>
	</div>
{/if}
