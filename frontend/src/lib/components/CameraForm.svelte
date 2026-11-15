<script lang="ts">
	// Add or edit a camera. The driver's option fields come from its JSON schema.
	import { api, type Camera, type Driver, type JsonSchemaProperty } from '../api';
	import { slugify } from '../format';
	import { store } from '../state.svelte';
	import { untrack } from 'svelte';

	interface Props {
		camera?: Camera;
		onsaved: (camera: Camera) => void;
	}
	let { camera, onsaved }: Props = $props();

	// The form edits a copy; the page re-creates it ({#key}) for another camera.
	const initial = untrack(() => camera);

	let drivers = $state<Driver[]>([]);
	let driverName = $state(initial?.driver ?? 'rtsp');
	let name = $state(initial?.name ?? '');
	let id = $state(initial?.id ?? '');
	let idEdited = $state(false);
	let enabled = $state(initial?.enabled ?? true);
	let record = $state<'off' | 'continuous'>(initial?.record ?? 'off');
	let options = $state<Record<string, string>>(
		Object.fromEntries(Object.entries(initial?.options ?? {}).map(([k, v]) => [k, String(v ?? '')]))
	);
	let saving = $state(false);
	let error = $state('');

	const driver = $derived(drivers.find((d) => d.name === driverName));
	const fields = $derived(Object.entries(driver?.options.properties ?? {}));
	const required = $derived(new Set(driver?.options.required ?? []));

	$effect(() => {
		api.drivers().then((d) => (drivers = d));
	});

	$effect(() => {
		if (!camera && !idEdited) id = slugify(name);
	});

	// Selects start at the driver's default.
	$effect(() => {
		for (const [key, prop] of fields) {
			if (options[key] === undefined && prop.default != null) options[key] = String(prop.default);
		}
	});

	function enumOf(prop: JsonSchemaProperty): string[] | undefined {
		return prop.enum ?? prop.anyOf?.find((p) => p.enum)?.enum;
	}

	function isSecret(key: string): boolean {
		return /pass|secret|token/i.test(key);
	}

	async function submit(e: SubmitEvent) {
		e.preventDefault();
		error = '';
		saving = true;
		const body: Record<string, unknown> = { name, driver: driverName, enabled, record };
		for (const [key] of fields) {
			const value = options[key]?.trim();
			if (value) body[key] = value;
		}
		try {
			const saved = camera
				? await api.updateCamera(camera.id, body)
				: await api.addCamera({ id, ...body });
			store.refresh();
			onsaved(saved);
		} catch (err) {
			error = err instanceof Error ? err.message : String(err);
		} finally {
			saving = false;
		}
	}
</script>

<form class="space-y-6" onsubmit={submit}>
	{#if !camera}
		<fieldset>
			<legend class="label">Type</legend>
			<div class="grid gap-2 sm:grid-cols-2">
				{#each drivers as d (d.name)}
					<label
						class="flex cursor-pointer flex-col gap-1 card p-4 transition has-[:checked]:border-accent/60 has-[:checked]:bg-accent/10"
					>
						<input type="radio" class="sr-only" bind:group={driverName} value={d.name} />
						<span class="text-sm font-semibold">{d.label}</span>
						<span class="text-xs text-muted">{d.description}</span>
					</label>
				{/each}
			</div>
		</fieldset>
	{/if}

	<div class="grid gap-4 sm:grid-cols-2">
		<div>
			<label class="label" for="cam-name">Name</label>
			<input id="cam-name" class="input" bind:value={name} required placeholder="Front door" />
		</div>
		<div>
			<label class="label" for="cam-id">ID</label>
			<input
				id="cam-id"
				class="input font-mono"
				bind:value={id}
				oninput={() => (idEdited = true)}
				disabled={!!camera}
				required
				pattern="[a-z0-9][a-z0-9\-]*"
				title="Lowercase letters, digits and dashes"
			/>
			<p class="mt-1 text-xs text-muted">
				The key in config.yaml and the folder of its recordings.
			</p>
		</div>
	</div>

	{#each fields as [key, prop] (key)}
		{@const choices = enumOf(prop)}
		<div>
			<label class="label" for="opt-{key}">
				{prop.title ?? key}
				{#if !required.has(key)}<span class="font-normal text-muted"> · optional</span>{/if}
			</label>
			{#if choices}
				<select id="opt-{key}" class="input" bind:value={options[key]}>
					{#each choices as choice (choice)}
						<option value={choice}>{choice}</option>
					{/each}
				</select>
			{:else}
				<input
					id="opt-{key}"
					class="input font-mono text-[13px]"
					type={isSecret(key) ? 'password' : 'text'}
					bind:value={options[key]}
					required={required.has(key)}
					placeholder={prop.default != null ? String(prop.default) : ''}
					autocomplete="off"
					spellcheck="false"
				/>
			{/if}
			{#if prop.description}<p class="mt-1 text-xs text-muted">{prop.description}</p>{/if}
		</div>
	{/each}

	<div class="divide-y divide-line card">
		<label class="flex cursor-pointer items-center justify-between gap-4 p-4">
			<span>
				<span class="block text-sm font-medium">Record continuously</span>
				<span class="block text-xs text-muted"
					>Keep everything, in files of a few minutes. Clips work either way.</span
				>
			</span>
			<input
				type="checkbox"
				class="size-5 accent-[var(--accent)]"
				checked={record === 'continuous'}
				onchange={(e) => (record = e.currentTarget.checked ? 'continuous' : 'off')}
			/>
		</label>
		<label class="flex cursor-pointer items-center justify-between gap-4 p-4">
			<span>
				<span class="block text-sm font-medium">Enabled</span>
				<span class="block text-xs text-muted"
					>A disabled camera stays in the config but doesn't connect.</span
				>
			</span>
			<input type="checkbox" class="size-5 accent-[var(--accent)]" bind:checked={enabled} />
		</label>
	</div>

	{#if error}
		<p class="rounded-xl bg-danger/10 px-4 py-3 text-sm text-danger">{error}</p>
	{/if}

	<div class="flex justify-end gap-2">
		<button type="button" class="btn-ghost" onclick={() => history.back()}>Cancel</button>
		<button type="submit" class="btn-primary" disabled={saving}>
			{saving ? 'Saving…' : camera ? 'Save' : 'Add camera'}
		</button>
	</div>
</form>
