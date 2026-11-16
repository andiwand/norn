<script lang="ts">
	// What each trigger records per day, and where that leads: measured once there is a week
	// (or an hour) of recordings, estimated from the settings and the bitrate before that.
	import { api, type Forecast } from '../api';
	import { formatBytes, triggerLabel } from '../format';
	import { store } from '../state.svelte';

	let forecast = $state<Forecast | null>(null);

	$effect(() => {
		const load = () =>
			api
				.forecast()
				.then((f) => (forecast = f))
				.catch(() => {});
		load();
		const timer = setInterval(load, 60_000);
		const off = store.on((e) => {
			if (e.type === 'settings.changed' || e.type === 'cameras.changed') load();
		});
		return () => {
			clearInterval(timer);
			off();
		};
	});

	function days(n: number): string {
		if (n < 1) return 'less than a day';
		if (Math.round(n) === 1) return '1 day';
		if (n < 60) return `${Math.round(n)} days`;
		if (n < 730) return `${Math.round(n / 30)} months`;
		return `${Math.round(n / 365)} years`;
	}
</script>

{#if forecast}
	{#if !forecast.triggers.length}
		<p class="text-sm text-muted">
			Nothing records on its own now. Clips you start, and their size, show here once there are
			some.
		</p>
	{:else}
		<div class="grid gap-3 sm:grid-cols-3">
			<div class="rounded-xl border border-line bg-surface-2/60 p-4">
				<div class="text-xs font-medium text-muted">Per day</div>
				<div class="mt-2 text-xl font-semibold tabular-nums">{formatBytes(forecast.per_day)}</div>
			</div>
			<div class="rounded-xl border border-line bg-surface-2/60 p-4">
				<div class="text-xs font-medium text-muted">Levels off at</div>
				<div class="mt-2 text-xl font-semibold tabular-nums">
					{forecast.retention_days ? formatBytes(forecast.steady) : '–'}
				</div>
				<p class="mt-1.5 text-xs text-muted">
					{#if forecast.retention_days}
						after {forecast.retention_days} days{forecast.growing_per_day
							? `, plus ${formatBytes(forecast.growing_per_day)} a day that stays`
							: ''}
					{:else}
						Nothing expires: it only grows.
					{/if}
				</p>
			</div>
			<div class="rounded-xl border border-line bg-surface-2/60 p-4">
				<div class="text-xs font-medium text-muted">Disk full</div>
				<div
					class="mt-2 text-xl font-semibold {forecast.days_until_full !== null &&
					forecast.days_until_full < 30
						? 'text-warning'
						: ''}"
				>
					{forecast.days_until_full === null ? 'Never' : `In ${days(forecast.days_until_full)}`}
				</div>
				<p class="mt-1.5 text-xs text-muted">at this rate</p>
			</div>
		</div>
		<div class="mt-3 overflow-x-auto">
			<table class="w-full text-sm">
				<thead>
					<tr class="border-b border-line text-left text-xs text-muted">
						<th class="py-2 pr-3 font-medium">Trigger</th>
						<th class="px-3 py-2 font-medium">Camera</th>
						<th class="px-3 py-2 text-right font-medium">Per day</th>
						<th class="py-2 pl-3 text-right font-medium">Levels off at</th>
					</tr>
				</thead>
				<tbody class="divide-y divide-line">
					{#each forecast.triggers as t (t.trigger)}
						{#each t.cameras as c, i (c.camera)}
							<tr>
								<td class="py-2 pr-3 font-medium">{i === 0 ? triggerLabel(t.trigger) : ''}</td>
								<td class="px-3 py-2 text-muted">
									{store.camera(c.camera)?.name ?? c.camera}
									{#if c.basis === 'estimated'}
										<span
											class="ml-1 rounded bg-surface-3 px-1 py-px text-[10px]"
											title="From the settings and the camera's bitrate, until there are recordings to measure"
											>estimate</span
										>
									{/if}
								</td>
								<td class="px-3 py-2 text-right tabular-nums">{formatBytes(c.per_day)}</td>
								<td class="py-2 pl-3 text-right text-muted tabular-nums">
									{c.steady === null ? 'stays' : formatBytes(c.steady)}
								</td>
							</tr>
						{/each}
					{/each}
				</tbody>
			</table>
			<p class="mt-2 text-xs text-muted">
				Measured from the last week of recordings; estimated from the settings and each camera's
				bitrate until there are some. Clips recorded by hand stay, so they only grow.
			</p>
		</div>
	{/if}
{/if}
