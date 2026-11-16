<script lang="ts">
	// Create or edit a circle: its name, its cameras, and settings for the cameras in it.
	import { untrack } from 'svelte';
	import { api, type Circle, type Window } from '../api';
	import { slugify } from '../format';
	import { store } from '../state.svelte';
	import IntervalSetting from './IntervalSetting.svelte';
	import TriggerSetting from './TriggerSetting.svelte';
	import ScheduleSetting from './ScheduleSetting.svelte';
	import NumberSetting from './NumberSetting.svelte';

	let { circle, onsaved }: { circle?: Circle; onsaved: (circle: Circle) => void } = $props();

	const initial = untrack(() => circle);
	let name = $state(initial?.name ?? '');
	let cameras = $state<string[]>([...(initial?.cameras ?? [])]);
	let pictureSeconds = $state<number | null>(initial?.picture_seconds ?? null);
	let triggers = $state<string[] | null>(initial?.triggers ?? null);
	let together = $state(initial?.together ?? false);
	let schedule = $state<Window[] | null>(initial?.schedule ?? null);
	const kinds = $derived([
		...new Set(cameras.flatMap((id) => store.camera(id)?.events?.kinds ?? []))
	]);
	let prebuffer = $state<number | null | undefined>(initial?.prebuffer_seconds ?? null);
	let saving = $state(false);
	let error = $state('');
	const globals = $derived(store.info?.recording);

	// Cameras of one driver are likely alike, so they can share their controls.
	const drivers = $derived(new Set(cameras.map((id) => store.camera(id)?.driver).filter(Boolean)));

	async function submit(e: SubmitEvent) {
		e.preventDefault();
		error = '';
		saving = true;
		const body = {
			name,
			cameras,
			picture_seconds: pictureSeconds,
			triggers,
			together,
			schedule,
			prebuffer_seconds:
				typeof prebuffer === 'number' && Number.isFinite(prebuffer) ? prebuffer : null
		};
		try {
			const saved = circle
				? await api.updateCircle(circle.id, body)
				: await api.addCircle({
						id: slugify(name) || `circle-${Date.now().toString(36)}`,
						...body
					});
			await store.refresh();
			onsaved(saved);
		} catch (err) {
			error = err instanceof Error ? err.message : String(err);
		} finally {
			saving = false;
		}
	}
</script>

<form class="@container space-y-6" onsubmit={submit}>
	<div>
		<label class="label" for="circle-name">Name</label>
		<input
			id="circle-name"
			class="input"
			bind:value={name}
			required
			placeholder="Outside, Ground floor, …"
		/>
	</div>

	<fieldset>
		<legend class="label">Cameras</legend>
		<div class="grid gap-2 @md:grid-cols-2">
			{#each store.cameras as camera (camera.id)}
				<label
					class="flex cursor-pointer items-center gap-3 card px-4 py-3 transition has-[:checked]:border-accent/60 has-[:checked]:bg-accent/10"
				>
					<input
						type="checkbox"
						class="size-4 accent-[var(--accent)]"
						bind:group={cameras}
						value={camera.id}
					/>
					<span class="min-w-0">
						<span class="block truncate text-sm font-medium">{camera.name}</span>
						<span class="block truncate text-xs text-muted"
							>{[camera.device?.manufacturer, camera.device?.model].filter(Boolean).join(' ') ||
								camera.driver}</span
						>
					</span>
				</label>
			{/each}
		</div>
		{#if cameras.length > 1}
			<p class="mt-2 text-xs text-muted">
				{drivers.size === 1
					? 'All of one kind: settings they share can be set for all at once.'
					: 'Different kinds: only settings they have in common can be set together.'}
			</p>
		{/if}
	</fieldset>

	<div class="divide-y divide-line card">
		<IntervalSetting
			label="Pictures"
			hint="For the cameras in this circle. A camera's own setting wins."
			bind:value={pictureSeconds}
			inherit={globals?.picture_seconds ?? 0}
		/>
		<TriggerSetting
			label="Record on detections"
			hint="For the cameras in this circle; a camera's own setting wins."
			bind:value={triggers}
			{kinds}
			inherit={globals?.triggers ?? []}
		/>
		<ScheduleSetting
			label="When detections record"
			bind:value={schedule}
			inherit={globals?.schedule ?? []}
		/>
		<label class="flex cursor-pointer items-center justify-between gap-4 px-5 py-3.5">
			<span>
				<span class="block text-sm font-medium">Record together</span>
				<span class="block text-xs text-muted"
					>When one camera here detects a trigger, all of them record.</span
				>
			</span>
			<input type="checkbox" role="switch" class="switch" bind:checked={together} />
		</label>
		<NumberSetting
			label="Record before the trigger"
			hint="Seconds a clip includes from before what started it. Empty: as set above; 0: off."
			bind:value={prebuffer}
			max={300}
			unit="sec"
			placeholder={globals ? String(globals.prebuffer_seconds) : ''}
		/>
	</div>

	{#if error}
		<p class="rounded-xl bg-danger/10 px-4 py-3 text-sm text-danger">{error}</p>
	{/if}

	<div class="flex justify-end gap-2">
		<a class="btn-ghost" href={circle ? `/circles/${circle.id}` : '/'}>Cancel</a>
		<button type="submit" class="btn-primary" disabled={saving || !name.trim()}>
			{saving ? 'Saving…' : circle ? 'Save' : 'Create circle'}
		</button>
	</div>
</form>
