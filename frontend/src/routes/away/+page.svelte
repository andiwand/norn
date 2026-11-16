<script lang="ts">
	// Away: for holidays. Detections record at any time, with their own triggers.
	import { store } from '#lib/state.svelte.js';
	import { SettingsForm } from '#lib/settings-form.svelte.js';
	import SaveBar from '#lib/components/SaveBar.svelte';
	import SettingsSection from '#lib/components/SettingsSection.svelte';
	import TriggerSetting from '#lib/components/TriggerSetting.svelte';
	import IntervalSetting from '#lib/components/IntervalSetting.svelte';
	import Plane from '@lucide/svelte/icons/plane';
	import CalendarRange from '@lucide/svelte/icons/calendar-range';
	import Zap from '@lucide/svelte/icons/zap';
	import X from '@lucide/svelte/icons/x';

	const settings = new SettingsForm();
	$effect(() => settings.watch());
	const form = $derived(settings.form);
	const info = $derived(store.info);
</script>

<svelte:head><title>Away · Norn</title></svelte:head>

<div class="mx-auto max-w-3xl space-y-5">
	<div class="flex flex-wrap items-end justify-between gap-3">
		<div>
			<h1 class="text-2xl font-semibold tracking-tight">Away</h1>
			<p class="mt-1 text-sm text-muted">
				For holidays: detections record at any time, regardless of their schedule.
			</p>
		</div>
		<span class="chip {info?.away.now ? 'chip-active' : ''}">
			<Plane class="size-3.5" />{info?.away.now ? 'Away now' : 'At home'}
		</span>
	</div>

	<SaveBar
		dirty={settings.dirty}
		saving={settings.saving}
		onsave={() => settings.save()}
		ondiscard={() => settings.reset()}
	/>

	{#if form}
		<SettingsSection
			title="When"
			description="Switch it on now (also in the header), or plan it ahead. Norn switches back by itself when the plan ends."
			icon={CalendarRange}
		>
			<label class="flex cursor-pointer items-center justify-between gap-4 px-5 py-3.5">
				<span>
					<span class="block text-sm font-medium">Away now</span>
					<span class="block text-xs text-muted">Until you switch it off.</span>
				</span>
				<input type="checkbox" role="switch" class="switch" bind:checked={form.away.active} />
			</label>
			<div class="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 px-5 py-3.5">
				<span class="min-w-0 flex-1 basis-56">
					<span class="block text-sm font-medium">Planned</span>
					<span class="block text-xs text-muted">Away from the first time until the second.</span>
					{#if form.away.start && form.away.end && form.away.end <= form.away.start}
						<span class="block text-xs text-warning"
							>It ends before it starts: it never applies.</span
						>
					{/if}
				</span>
				<span class="flex w-full flex-wrap items-center justify-end gap-1.5 text-sm sm:w-auto">
					<input
						type="datetime-local"
						class="field h-9 px-2"
						aria-label="Away from"
						value={form.away.start?.slice(0, 16) ?? ''}
						onchange={(e) => (form!.away.start = e.currentTarget.value || null)}
					/>
					<span class="text-muted">to</span>
					<input
						type="datetime-local"
						class="field h-9 px-2"
						aria-label="Away until"
						value={form.away.end?.slice(0, 16) ?? ''}
						onchange={(e) => (form!.away.end = e.currentTarget.value || null)}
					/>
					{#if form.away.start || form.away.end}
						<button
							type="button"
							class="icon-btn size-8"
							aria-label="Clear the plan"
							onclick={() => {
								form!.away.start = null;
								form!.away.end = null;
							}}><X class="size-4" /></button
						>
					{/if}
				</span>
			</div>
		</SettingsSection>

		<SettingsSection
			title="What records while away"
			description="On every camera. Leave them empty to use the usual triggers, at any time of day."
			icon={Zap}
		>
			<TriggerSetting
				label="Record on"
				hint="What starts a clip while away."
				bind:value={form.away.triggers as string[] | null}
			/>
			<IntervalSetting
				label="Pictures"
				hint="Off: as usual."
				bind:value={form.away.picture_seconds}
			/>
		</SettingsSection>
	{:else}
		<div class="h-64 animate-pulse rounded-2xl bg-surface-2"></div>
	{/if}
</div>
