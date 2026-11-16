<script lang="ts">
	// How other software watches and steers this camera through Norn: one connection to the
	// camera, no camera password. With a Home Assistant setup to copy.
	import type { Camera, Control } from '../api';
	import { store } from '../state.svelte';
	import Copy from '@lucide/svelte/icons/copy';
	import Check from '@lucide/svelte/icons/check';

	let { camera, controls }: { camera: Camera; controls: Control[] } = $props();

	const origin = location.origin;
	const host = location.hostname;
	const api = $derived(`${origin}/api/cameras/${camera.id}`);
	const rtsp = $derived(store.info?.rtsp);
	const ptz = $derived(camera.capabilities.includes('ptz'));
	const presets = $derived(Object.entries(camera.presets_norn ?? {}));
	const settable = $derived(controls.filter((c) => c.kind !== 'button'));
	const buttons = $derived(controls.filter((c) => c.kind === 'button'));
	const kinds = $derived(camera.events?.kinds ?? []);
	const slug = $derived(camera.id.replaceAll('-', '_'));
	const main = $derived(camera.streams.find((s) => !s.transcoded) ?? camera.streams[0]);

	const watch = $derived([
		...(rtsp?.shared
			? camera.streams.map((s) => ({
					label: `Video, ${s.label}${s.transcoded ? ' (made by Norn)' : ''}`,
					value: `rtsp://${host}:${rtsp.port}/${s.name}`
				}))
			: []),
		{ label: 'Picture now', value: `${api}/still.jpg` },
		{ label: 'Pictures as a stream (MJPEG)', value: `${api}/stills?every=1` },
		{ label: 'Full-size snapshot', value: `${api}/snapshot` }
	]);

	const control = $derived([
		{
			label: 'Record a clip',
			value: `curl -X POST ${api}/record -H 'Content-Type: application/json' -d '{"trigger": "home-assistant"}'`
		},
		{ label: 'Stop the clip', value: `curl -X DELETE ${api}/record` },
		...presets.map(([id, p]) => ({
			label: `Go to “${p.name}”`,
			value: `curl -X POST ${api}/presets/${id}/goto`
		})),
		...(ptz
			? [
					{
						label: 'Turn (pan, tilt and zoom from −1 to 1; stops by itself)',
						value: `curl -X POST ${api}/ptz -H 'Content-Type: application/json' -d '{"action": "move", "pan": 0.5}'`
					}
				]
			: []),
		...settable.map((c) => ({
			label: `${c.label}${c.options?.length ? ` (${c.options.map((o) => o.value).join(', ')})` : c.kind === 'range' ? ` (${c.min} to ${c.max})` : ''}`,
			value: `curl -X POST ${api}/controls/${c.id} -H 'Content-Type: application/json' -d '{"value": ${JSON.stringify(c.value ?? null)}}'`
		})),
		...buttons.map((c) => ({
			label: c.label,
			value: `curl -X POST ${api}/controls/${c.id} -H 'Content-Type: application/json' -d '{}'`
		})),
		{
			label: 'Its state: recording, what it detects now (events.active), …',
			value: `curl ${api}`
		}
	]);

	const yaml = $derived(
		[
			'rest_command:',
			`  ${slug}_record:`,
			`    url: ${api}/record`,
			'    method: post',
			'    content_type: application/json',
			`    payload: '{"trigger": "home-assistant"}'`,
			`  ${slug}_stop:`,
			`    url: ${api}/record`,
			'    method: delete',
			...(presets.length
				? [
						`  ${slug}_preset: # data: {preset: ${presets.map(([id]) => id).join(' | ')}}`,
						`    url: "${api}/presets/{{ preset }}/goto"`,
						'    method: post'
					]
				: []),
			'',
			'rest:',
			`  - resource: ${api}`,
			'    scan_interval: 5',
			'    binary_sensor:',
			`      - name: ${camera.name} recording`,
			'        value_template: "{{ value_json.recording is not none }}"',
			...kinds.map((k) =>
				[
					`      - name: ${camera.name} ${k}`,
					`        value_template: "{{ '${k}' in ((value_json.events or {}).active or []) }}"`
				].join('\n')
			)
		].join('\n')
	);

	let copied = $state('');
	async function copy(text: string) {
		try {
			await navigator.clipboard.writeText(text);
		} catch {
			// Plain http (not localhost) has no clipboard API: the old way.
			const area = document.createElement('textarea');
			area.value = text;
			document.body.append(area);
			area.select();
			document.execCommand('copy');
			area.remove();
		}
		copied = text;
		setTimeout(() => copied === text && (copied = ''), 1500);
	}
</script>

{#snippet line(item: { label: string; value: string })}
	<div class="py-2">
		<div class="mb-1 text-xs text-muted">{item.label}</div>
		<div class="flex items-start gap-2">
			<code
				class="min-w-0 flex-1 rounded-lg bg-surface-2 px-2.5 py-1.5 font-mono text-xs break-all select-all"
				>{item.value}</code
			>
			<button
				class="icon-btn size-8 shrink-0"
				aria-label="Copy {item.label}"
				onclick={() => copy(item.value)}
			>
				{#if copied === item.value}<Check class="size-4 text-accent" />{:else}<Copy
						class="size-4"
					/>{/if}
			</button>
		</div>
	</div>
{/snippet}

<p class="text-sm text-muted">
	Home Assistant, or anything else on your network, can watch and steer this camera through Norn:
	the camera keeps one connection, to Norn, and its password stays here.
</p>

<h3 class="mt-4 eyebrow">Watch</h3>
{#if rtsp && !rtsp.shared}
	<p class="my-2 rounded-xl bg-surface-2 px-3 py-2 text-xs text-muted">
		The video (RTSP) is only for Norn now. To share it on your network, start Norn with
		<code class="font-mono text-text">NORN_RTSP_SHARE=1</code>; its addresses then show here.
		Without it, the pictures below work too.
	</p>
{/if}
<div class="divide-y divide-line">
	{#each watch as item (item.value)}{@render line(item)}{/each}
</div>

<h3 class="mt-4 eyebrow">Control</h3>
<div class="divide-y divide-line">
	{#each control as item (item.value)}{@render line(item)}{/each}
</div>

<h3 class="mt-4 eyebrow">Home Assistant</h3>
<ol class="mt-2 list-decimal space-y-1.5 pl-5 text-sm">
	<li>
		Settings → Devices & services → Add integration → <b>Generic Camera</b>. Still image URL:
		<code class="font-mono text-xs break-all">{api}/still.jpg</code>{#if rtsp?.shared && main};
			stream source:
			<code class="font-mono text-xs break-all">rtsp://{host}:{rtsp.port}/{main.name}</code>{:else};
			or <b>MJPEG IP Camera</b> with
			<code class="font-mono text-xs break-all">{api}/stills?every=1</code>{/if}.
	</li>
	<li>
		Buttons and sensors: add this to <code class="font-mono text-xs">configuration.yaml</code> and
		restart. Call <code class="font-mono text-xs">rest_command.{slug}_record</code> from an automation
		or a button.
	</li>
</ol>
<div class="relative mt-2">
	<pre
		class="overflow-x-auto rounded-xl bg-surface-2 p-3 pr-12 font-mono text-xs leading-relaxed">{yaml}</pre>
	<button
		class="absolute top-2 right-2 icon-btn size-8"
		aria-label="Copy the Home Assistant configuration"
		onclick={() => copy(yaml)}
	>
		{#if copied === yaml}<Check class="size-4 text-accent" />{:else}<Copy class="size-4" />{/if}
	</button>
</div>
<p class="mt-2 text-xs text-muted">
	Norn has no login: keep it in your home network. All of its API is described at
	<a href="/api/docs" target="_blank" class="text-accent hover:underline">/api/docs</a>.
</p>
