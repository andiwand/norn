<script lang="ts">
	// What makes Norn record, for all cameras: detections and their schedule, clips, pictures,
	// and Norn's own detection. Circles, cameras and presets can set their own; the list at the
	// end shows where they do. Away mode has its own triggers, on its page.
	import type { Window } from '#lib/api.js';
	import { store } from '#lib/state.svelte.js';
	import { ownSettings } from '#lib/format.js';
	import { SettingsForm } from '#lib/settings-form.svelte.js';
	import SaveBar from '#lib/components/SaveBar.svelte';
	import SettingsSection from '#lib/components/SettingsSection.svelte';
	import NumberSetting from '#lib/components/NumberSetting.svelte';
	import IntervalSetting from '#lib/components/IntervalSetting.svelte';
	import TriggerSetting from '#lib/components/TriggerSetting.svelte';
	import ScheduleSetting from '#lib/components/ScheduleSetting.svelte';
	import ChoiceSetting from '#lib/components/ChoiceSetting.svelte';
	import Zap from '@lucide/svelte/icons/zap';
	import Clapperboard from '@lucide/svelte/icons/clapperboard';
	import Image from '@lucide/svelte/icons/image';
	import ScanEye from '@lucide/svelte/icons/scan-eye';
	import Layers from '@lucide/svelte/icons/layers';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';

	const settings = new SettingsForm();
	$effect(() => settings.watch());
	const form = $derived(settings.form);
	const defaults = $derived(settings.defaults);

	const info = $derived(store.info);
	const clockDiffers = $derived(
		!!info?.time && info.time.offset_minutes !== -new Date().getTimezoneOffset()
	);
	function offset(minutes: number): string {
		const sign = minutes < 0 ? '−' : '+';
		const m = Math.abs(minutes);
		return `${sign}${Math.floor(m / 60)}${m % 60 ? `:${String(m % 60).padStart(2, '0')}` : ''}`;
	}

	const overrides = $derived([
		...store.circles.map((c) => ({
			key: `circle:${c.id}`,
			href: `/circles/${c.id}`,
			name: c.name,
			kind: 'Circle',
			parts: [...ownSettings(c), ...(c.together ? ['records together'] : [])]
		})),
		...store.cameras.flatMap((c) => [
			{
				key: `camera:${c.id}`,
				href: `/cameras/${c.id}`,
				name: c.name,
				kind: 'Camera',
				parts: ownSettings(c)
			},
			...Object.entries(c.presets_norn ?? {}).map(([id, p]) => ({
				key: `preset:${c.id}/${id}`,
				href: `/cameras/${c.id}`,
				name: `${c.name} · ${p.name}`,
				kind: 'Preset',
				parts: ownSettings(p)
			}))
		])
	]);
	const changed = $derived(overrides.filter((o) => o.parts.length));
</script>

<svelte:head><title>Triggers · Norn</title></svelte:head>

<div class="mx-auto max-w-3xl space-y-5">
	<div>
		<h1 class="page-title">Triggers</h1>
		<p class="page-intro">
			What makes Norn record, for every camera. Circles, cameras and their presets can set their
			own; <a href="/away" class="text-accent hover:underline">Away</a> has its own triggers.
		</p>
	</div>

	<SaveBar
		dirty={settings.dirty}
		saving={settings.saving}
		onsave={() => settings.save()}
		ondiscard={() => settings.reset()}
	/>

	{#if form && defaults}
		<SettingsSection
			title="What records"
			description="Detections that start a clip, from the cameras themselves or from Norn. A clip runs while the detection lasts, plus the clip length; a new trigger during a clip makes it longer."
			icon={Zap}
		>
			<TriggerSetting label="Record on" bind:value={form.recording.triggers} />
			{#if clockDiffers}
				<p class="mx-5 my-3 rounded-xl bg-warning/10 px-3 py-2 text-xs text-warning">
					Norn's clock runs in {info?.time.zone} (UTC{offset(info?.time.offset_minutes ?? 0)}), this
					browser in UTC{offset(-new Date().getTimezoneOffset())}. Schedules follow Norn's clock:
					set <code class="font-mono">TZ</code> to your time zone.
				</p>
			{/if}
			<ScheduleSetting
				label="When"
				hint="Only in these times, e.g. at night. Away mode records at any time."
				bind:value={form.recording.schedule as Window[] | null}
			/>
		</SettingsSection>

		<SettingsSection
			title="Clips"
			description="How long a clip runs after its trigger, and how much of before it includes."
			icon={Clapperboard}
		>
			{#snippet aside()}
				{#if info && !info.recording_available}
					<span class="text-xs text-danger">Recording is off: needs go2rtc and FFmpeg</span>
				{/if}
			{/snippet}
			<NumberSetting
				label="Clip length"
				hint="After a button, a webhook, or the end of a detection."
				bind:value={form.recording.clip_seconds}
				fallback={defaults.recording.clip_seconds}
				min={5}
				max={3600}
				unit="sec"
			/>
			<NumberSetting
				label="Record before the trigger"
				hint="Each camera's last seconds wait in RAM. MJPEG cameras only when set on the camera. 0: off."
				bind:value={form.recording.prebuffer_seconds}
				fallback={defaults.recording.prebuffer_seconds}
				max={300}
				unit="sec"
			/>
		</SettingsSection>

		<SettingsSection
			title="Pictures"
			description="A picture of every camera on a timer, at any hour. They expire like other automatic recordings."
			icon={Image}
		>
			<IntervalSetting label="Take a picture" bind:value={form.recording.picture_seconds} />
		</SettingsSection>

		<SettingsSection
			title="Detection by Norn"
			description="Besides what the cameras detect themselves, Norn can look at a still of each camera every few seconds. What it finds becomes the same triggers."
			icon={ScanEye}
		>
			<ChoiceSetting
				label="Motion"
				hint="Compares the stills. Costs almost nothing."
				bind:value={form.detection.motion}
				choices={[
					[false, 'Off'],
					[true, 'On']
				]}
			/>
			<ChoiceSetting
				label="People, vehicles, animals"
				hint={info?.detection.objects_unavailable
					? `Not available: ${info.detection.objects_unavailable}.`
					: 'A small AI model on the CPU, about 20 ms per still.'}
				bind:value={form.detection.objects}
				disabled={!!info?.detection.objects_unavailable}
				choices={[
					[false, 'Off'],
					[true, 'On']
				]}
			/>
			<NumberSetting
				label="Look every"
				hint="How often Norn checks a still of each camera."
				bind:value={form.detection.every_seconds}
				fallback={defaults.detection.every_seconds}
				min={0.5}
				max={60}
				step={0.5}
				unit="sec"
			/>
			<ChoiceSetting
				label="Stills"
				hint="Keyframes cost next to nothing but come every few seconds; every frame is exact and uses more CPU."
				bind:value={form.detection.stills}
				choices={[
					['auto', 'Auto'],
					['keyframe', 'Keyframes'],
					['live', 'Every frame']
				]}
			/>
			<NumberSetting
				label="Motion sensitivity"
				hint="Higher reacts to smaller changes."
				bind:value={form.detection.sensitivity}
				fallback={defaults.detection.sensitivity}
				max={100}
				unit="%"
			/>
			<NumberSetting
				label="Certainty"
				hint="How sure the AI must be about an object (0.1 to 0.95)."
				bind:value={form.detection.min_score}
				fallback={defaults.detection.min_score}
				min={0.1}
				max={0.95}
				step={0.05}
			/>
			<ChoiceSetting
				label="Model"
				hint="Tiny finds more, at about four times the CPU."
				bind:value={form.detection.model}
				choices={[
					['nano', 'Nano'],
					['tiny', 'Tiny']
				]}
			/>
		</SettingsSection>

		<SettingsSection
			title="Set their own"
			description="Circles, cameras and presets that differ from the above. A preset's settings count while the camera is there; a camera's beat its circle's."
			icon={Layers}
		>
			{#each changed as o (o.key)}
				<a href={o.href} class="flex items-center gap-3 px-5 py-3 transition hover:bg-surface-2">
					<span class="min-w-0 flex-1">
						<span class="block truncate text-sm font-medium"
							>{o.name} <span class="font-normal text-muted">· {o.kind}</span></span
						>
						<span class="block truncate text-xs text-muted">{o.parts.join(' · ')}</span>
					</span>
					<ChevronRight class="size-4 shrink-0 text-muted" />
				</a>
			{:else}
				<p class="px-5 py-4 text-sm text-muted">
					None: every camera records as set above. Set a camera's own under “Recording & triggers”
					on its page.
				</p>
			{/each}
		</SettingsSection>
	{:else}
		<div class="h-64 animate-pulse rounded-2xl bg-surface-2"></div>
	{/if}
</div>
