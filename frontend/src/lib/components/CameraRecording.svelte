<script lang="ts">
	// What a camera records and when: its own values over its circle's and the global ones, and
	// for a pan/tilt camera, each preset's over the camera's. One Save for all of it.
	import { untrack } from 'svelte';
	import {
		api,
		cameraBody,
		type Camera,
		type DetectionSettings,
		type PresetRecording,
		type Window
	} from '../api';
	import { numberOrNull } from '../format';
	import { store } from '../state.svelte';
	import ChoiceSetting from './ChoiceSetting.svelte';
	import IntervalSetting from './IntervalSetting.svelte';
	import NumberSetting from './NumberSetting.svelte';
	import ScheduleSetting from './ScheduleSetting.svelte';
	import TriggerSetting from './TriggerSetting.svelte';

	let { camera }: { camera: Camera } = $props();

	// The page re-creates this ({#key}) for another camera.
	const initial = untrack(() => camera);

	let record = $state(initial.record);
	let pictureSeconds = $state(initial.picture_seconds);
	let triggers = $state(initial.triggers);
	let schedule = $state<Window[] | null>(initial.schedule);
	let clip = $state<number | null | undefined>(initial.clip_seconds);
	let prebuffer = $state<number | null | undefined>(initial.prebuffer_seconds);
	let detectMotion = $state<boolean | null>(initial.detection?.motion ?? null);
	let detectObjects = $state<boolean | null>(initial.detection?.objects ?? null);
	let detectStills = $state<DetectionSettings['stills'] | null>(initial.detection?.stills ?? null);
	let detectEvery = $state<number | null | undefined>(initial.detection?.every_seconds ?? null);
	let presets = $state<Record<string, PresetRecording>>(
		Object.fromEntries(
			Object.entries(initial.presets_norn ?? {}).map(([id, p]) => [
				id,
				{
					triggers: p.triggers ?? null,
					clip_seconds: p.clip_seconds ?? null,
					prebuffer_seconds: p.prebuffer_seconds ?? null
				}
			])
		)
	);
	let saving = $state(false);

	const detection = $derived.by(() => {
		// Fields not shown here (sensitivity, certainty, ...) stay as they are.
		const d: Record<string, unknown> = {
			...initial.detection,
			motion: detectMotion,
			objects: detectObjects,
			stills: detectStills,
			every_seconds: numberOrNull(detectEvery)
		};
		const set = Object.fromEntries(Object.entries(d).filter(([, v]) => v !== null));
		return Object.keys(set).length ? set : null;
	});

	const own = $derived({
		record,
		picture_seconds: pictureSeconds,
		triggers,
		schedule,
		clip_seconds: numberOrNull(clip),
		prebuffer_seconds: numberOrNull(prebuffer),
		detection
	});
	// What was saved last, to tell what changed.
	let before = $state({
		record: initial.record,
		picture_seconds: initial.picture_seconds,
		triggers: initial.triggers,
		schedule: initial.schedule,
		clip_seconds: initial.clip_seconds,
		prebuffer_seconds: initial.prebuffer_seconds,
		detection: initial.detection
	});
	let presetsBefore = $state(JSON.stringify(presets));
	const cleanPresets = $derived(
		Object.fromEntries(
			Object.entries(presets).map(([id, p]) => [
				id,
				{
					triggers: p.triggers,
					clip_seconds: numberOrNull(p.clip_seconds),
					prebuffer_seconds: numberOrNull(p.prebuffer_seconds)
				}
			])
		)
	);
	const cameraDirty = $derived(JSON.stringify(own) !== JSON.stringify(before));
	const dirty = $derived(cameraDirty || JSON.stringify(cleanPresets) !== presetsBefore);

	// Without a value of its own: its first circle's, else the global one (as the server does).
	const globals = $derived(store.info?.recording);
	const circle = $derived(store.circles.find((c) => c.cameras.includes(initial.id)));
	const inherited = $derived({
		triggers: circle?.triggers ?? globals?.triggers ?? [],
		schedule: circle?.schedule ?? globals?.schedule ?? [],
		picture_seconds: circle?.picture_seconds ?? globals?.picture_seconds ?? 0,
		prebuffer_seconds: circle?.prebuffer_seconds ?? globals?.prebuffer_seconds ?? 0,
		clip_seconds: circle?.clip_seconds ?? globals?.clip_seconds ?? 30
	});
	// What a preset without its own value gets: the camera's.
	const cameraValue = $derived({
		triggers: triggers ?? inherited.triggers,
		clip_seconds: numberOrNull(clip) ?? inherited.clip_seconds,
		prebuffer_seconds: numberOrNull(prebuffer) ?? inherited.prebuffer_seconds
	});

	async function save() {
		saving = true;
		const ok = await store.attempt(async () => {
			if (cameraDirty) await api.updateCamera(camera.id, cameraBody(camera, own));
			const was = JSON.parse(presetsBefore) as Record<string, PresetRecording>;
			for (const [id, p] of Object.entries(cleanPresets)) {
				if (JSON.stringify(p) !== JSON.stringify(was[id]) && camera.presets_norn[id])
					await api.setPresetRecording(camera.id, id, p);
			}
			return true;
		}, 'Saved');
		saving = false;
		if (ok) {
			before = $state.snapshot(own);
			presetsBefore = JSON.stringify(cleanPresets);
			store.refresh();
		}
	}
</script>

<div class="-mx-4 divide-y divide-line border-y border-line">
	<label class="flex cursor-pointer items-center justify-between gap-4 px-5 py-3.5">
		<span>
			<span class="block text-sm font-medium">Record continuously</span>
			<span class="block text-xs text-muted"
				>Keep everything, in files of a few minutes. Clips work either way.</span
			>
		</span>
		<input
			type="checkbox"
			role="switch"
			class="switch"
			checked={record === 'continuous'}
			onchange={(e) => (record = e.currentTarget.checked ? 'continuous' : 'off')}
		/>
	</label>
	<IntervalSetting
		label="Pictures"
		hint="A picture on a timer. They expire like other automatic recordings."
		bind:value={pictureSeconds}
		inherit={inherited.picture_seconds}
	/>
	{#if camera.events}
		<TriggerSetting
			label="Record on"
			hint="What this camera detects that starts a clip."
			bind:value={triggers}
			kinds={camera.events.kinds}
			inherit={inherited.triggers}
		/>
		<ScheduleSetting
			label="When detections record"
			bind:value={schedule}
			inherit={inherited.schedule}
		/>
	{/if}
	<NumberSetting
		label="Clip length"
		hint="After a button, a webhook, or the end of a detection. Empty: as set above."
		bind:value={clip}
		min={5}
		max={3600}
		unit="sec"
		placeholder={String(inherited.clip_seconds)}
	/>
	<NumberSetting
		label="Record before the trigger"
		hint="Seconds a clip includes from before what started it. Empty: as set above; 0: off."
		bind:value={prebuffer}
		max={300}
		unit="sec"
		placeholder={String(inherited.prebuffer_seconds)}
	/>
	<ChoiceSetting
		label="Motion by Norn"
		hint="Norn compares stills of this camera."
		bind:value={detectMotion}
		choices={[
			[null, 'Default'],
			[true, 'On'],
			[false, 'Off']
		]}
	/>
	<ChoiceSetting
		label="Objects by Norn"
		hint={store.info?.detection.objects_unavailable
			? `Not available: ${store.info.detection.objects_unavailable}.`
			: "People, vehicles and animals, by Norn's AI."}
		bind:value={detectObjects}
		disabled={!!store.info?.detection.objects_unavailable}
		choices={[
			[null, 'Default'],
			[true, 'On'],
			[false, 'Off']
		]}
	/>
	<ChoiceSetting
		label="Stills"
		hint="For pictures and Norn's detection."
		bind:value={detectStills}
		choices={[
			[null, 'Default'],
			['auto', 'Auto'],
			['keyframe', 'Keyframes'],
			['live', 'Every frame']
		]}
	/>
	<NumberSetting
		label="Look every"
		hint="How often Norn checks a still. Empty: as set above."
		bind:value={detectEvery}
		min={0.5}
		max={60}
		step={0.5}
		unit="sec"
		placeholder={String(store.info?.detection.every_seconds ?? '')}
	/>
</div>

{#each Object.entries(camera.presets_norn ?? {}) as [id, preset] (id)}
	{#if presets[id]}
		<h3 class="mt-5 mb-1 text-xs font-medium text-muted">
			At “{preset.name}” <span class="font-normal">· empty: as for the camera</span>
		</h3>
		<div class="-mx-4 divide-y divide-line border-y border-line">
			{#if camera.events}
				<TriggerSetting
					label="Record on"
					bind:value={presets[id].triggers}
					kinds={camera.events.kinds}
					inherit={cameraValue.triggers}
				/>
			{/if}
			<NumberSetting
				label="Clip length"
				bind:value={presets[id].clip_seconds}
				min={5}
				max={3600}
				unit="sec"
				placeholder={String(cameraValue.clip_seconds)}
			/>
			<NumberSetting
				label="Record before the trigger"
				bind:value={presets[id].prebuffer_seconds}
				max={300}
				unit="sec"
				placeholder={String(cameraValue.prebuffer_seconds)}
			/>
		</div>
	{/if}
{/each}

<div class="mt-4 flex items-center justify-end gap-3">
	<span class="mr-auto text-xs text-muted"
		>Defaults are on the <a href="/triggers" class="text-accent hover:underline">Triggers</a> page.</span
	>
	<button class="btn-primary" disabled={!dirty || saving} onclick={save}
		>{saving ? 'Saving…' : 'Save'}</button
	>
</div>
