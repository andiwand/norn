<script lang="ts">
	// Two tiny gauges for the top bar, like a battery: how full the recordings disk is and how
	// busy the machine's CPU is. They link to Diagnostics, which has the details.
	import { api } from '../api';
	import { formatBytes } from '../format';
	import HardDrive from '@lucide/svelte/icons/hard-drive';
	import Cpu from '@lucide/svelte/icons/cpu';

	let disk = $state<{ share: number; free: number | null; total: number } | null>(null);
	let cpu = $state<number | null>(null);

	$effect(() => {
		const loadDisk = () =>
			api
				.storage()
				.then(({ recordings: s }) => {
					disk = s.total
						? {
								share: s.free !== null ? ((s.total - s.free) / s.total) * 100 : 0,
								free: s.free,
								total: s.total
							}
						: null;
				})
				.catch(() => {});
		const loadCpu = () =>
			api
				.resources()
				.then((r) => (cpu = r.system.cpu))
				.catch(() => {});
		// Only while the page is visible: a phone in a pocket doesn't need to ask.
		const tick = (n: number) => {
			if (document.hidden) return;
			loadCpu();
			if (n % 4 === 0) loadDisk();
		};
		let n = 0;
		tick(n);
		const timer = setInterval(() => tick(++n), 15_000);
		const visible = () => tick(0);
		document.addEventListener('visibilitychange', visible);
		return () => {
			clearInterval(timer);
			document.removeEventListener('visibilitychange', visible);
		};
	});

	const tone = (v: number, warn: number, bad: number) =>
		v >= bad ? 'bg-danger' : v >= warn ? 'bg-warning' : 'bg-accent';

	const title = $derived(
		[
			disk &&
				`Recordings disk ${disk.share.toFixed(0)} % full${disk.free !== null ? ` (${formatBytes(disk.free)} free of ${formatBytes(disk.total)})` : ''}`,
			cpu !== null && `CPU ${cpu.toFixed(0)} % (the whole machine)`
		]
			.filter(Boolean)
			.join('\n')
	);
</script>

{#if disk || cpu !== null}
	<a
		href="/diagnostics"
		class="flex h-8 shrink-0 items-center gap-2 rounded-full px-1 text-muted transition hover:text-text"
		{title}
		aria-label={title}
	>
		{#each [{ icon: HardDrive, value: disk?.share, warn: 85, bad: 95 }, { icon: Cpu, value: cpu, warn: 70, bad: 90 }] as g, i (i)}
			{#if g.value !== undefined && g.value !== null}
				<span class="flex items-center gap-0.5">
					<g.icon class="size-3.5" />
					<!-- The battery: a body with a fill, and a nub on the right. -->
					<span class="flex items-center">
						<span class="h-2.5 w-5 overflow-hidden rounded-[3px] border border-current p-px">
							<span
								class="block h-full rounded-[1px] {tone(g.value, g.warn, g.bad)}"
								style:width="{Math.max(8, Math.min(100, g.value))}%"
							></span>
						</span>
						<span class="h-1 w-px rounded-r-sm bg-current"></span>
					</span>
				</span>
			{/if}
		{/each}
	</a>
{/if}
