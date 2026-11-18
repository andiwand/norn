<script lang="ts">
	// Cameras in the network, to add with a click: Norn asks around (ONVIF's WS-Discovery) when
	// the page opens, and can ask one address directly (for cameras without ONVIF, or where
	// multicast doesn't reach: another subnet, a VPN, Docker's bridge network). Choosing one fills
	// in the form below; the password is left to type.
	import { api, type Driver, type FoundCamera } from '../api';
	import Radar from '@lucide/svelte/icons/radar';
	import LoaderCircle from '@lucide/svelte/icons/loader-circle';
	import Search from '@lucide/svelte/icons/search';
	import Check from '@lucide/svelte/icons/check';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';

	let { drivers, onpick }: { drivers: Driver[]; onpick: (found: FoundCamera) => void } = $props();

	let scanning = $state(false);
	let scanned = $state(false);
	let failed = $state('');
	let container = $state(false);
	let found = $state<FoundCamera[]>([]);
	let picked = $state<string | null>(null);

	let address = $state('');
	let checking = $state(false);
	let checked = $state<'none' | 'error' | null>(null);
	let checkError = $state('');

	async function scan() {
		scanning = true;
		failed = '';
		try {
			const result = await api.discover(3);
			container = result.container;
			// Keep what was found by address before (a second scan may miss one).
			const byHost = new Map(found.map((f) => [f.host, f]));
			for (const f of result.devices) byHost.set(f.host, f);
			found = [...byHost.values()];
		} catch (e) {
			failed = e instanceof Error ? e.message : String(e);
		} finally {
			scanning = false;
			scanned = true;
		}
	}

	$effect(() => {
		scan();
	});

	async function check(e: SubmitEvent) {
		e.preventDefault();
		const host = address.trim();
		if (!host) return;
		checking = true;
		checked = null;
		try {
			const { device } = await api.checkAddress(host);
			if (device) {
				found = [device, ...found.filter((f) => f.host !== device.host)];
				choose(device);
				address = '';
			} else checked = 'none';
		} catch (err) {
			checked = 'error';
			checkError = err instanceof Error ? err.message : String(err);
		} finally {
			checking = false;
		}
	}

	function choose(f: FoundCamera) {
		picked = f.host;
		onpick(f);
	}

	const label = (name: string) => drivers.find((d) => d.name === name)?.label ?? name;
	const title = (f: FoundCamera) =>
		[f.manufacturer, f.hardware].filter(Boolean).join(' ') || f.name || 'ONVIF camera';
</script>

<section class="card p-4 sm:p-5" aria-labelledby="find-title">
	<div class="flex items-center gap-3">
		<span class="grid size-9 shrink-0 place-items-center rounded-xl bg-accent/12 text-accent">
			<Radar class="size-5" />
		</span>
		<div class="min-w-0 flex-1">
			<h2 id="find-title" class="text-sm font-semibold">Find cameras</h2>
			<p class="text-xs text-muted">
				{#if scanning}Looking in your network…{:else if found.length}Pick one to fill in the form
					below.{:else}Cameras that answer ONVIF show up here.{/if}
			</p>
		</div>
		<button type="button" class="btn-ghost h-9 shrink-0" onclick={scan} disabled={scanning}>
			{#if scanning}<LoaderCircle class="size-4 animate-spin" />Looking…{:else}Look again{/if}
		</button>
	</div>

	{#if found.length}
		<ul class="mt-4 grid gap-2 sm:grid-cols-2">
			{#each found as f (f.host)}
				<li>
					<button
						type="button"
						class="flex w-full items-center gap-3 rounded-xl border px-3 py-2.5 text-left transition {picked ===
						f.host
							? 'border-accent/60 bg-accent/10'
							: 'border-line bg-surface-2/50 hover:border-line-strong'}"
						onclick={() => choose(f)}
						aria-pressed={picked === f.host}
					>
						<span class="min-w-0 flex-1">
							<span class="block truncate text-sm font-medium">{title(f)}</span>
							<span class="block truncate text-xs text-muted tabular-nums">
								<!-- The port is ONVIF's: it matters only to the ONVIF driver. -->
								{f.host}{f.driver === 'onvif' && f.port !== 80 ? `:${f.port}` : ''} · {label(
									f.driver
								)}
							</span>
						</span>
						{#if f.camera}
							<span
								class="shrink-0 rounded-full bg-surface-3 px-2 py-0.5 text-[11px] font-medium text-muted"
								title="A camera at this address is set up already: “{f.camera}”">Added</span
							>
						{:else if picked === f.host}
							<Check class="size-4 shrink-0 text-accent" />
						{:else}
							<ChevronRight class="size-4 shrink-0 text-muted" />
						{/if}
					</button>
				</li>
			{/each}
		</ul>
	{:else if scanned && !scanning}
		<p class="mt-4 rounded-xl bg-surface-2/60 px-3 py-2.5 text-sm text-muted">
			{#if failed}
				Looking didn't work: {failed}
			{:else if container}
				No camera answered. In Docker, finding cameras needs host networking (<code
					class="font-mono text-xs">network_mode: host</code
				>); you can still check an address below.
			{:else}
				No camera answered. Many cameras answer only with ONVIF switched on in their settings;
				others Norn can recognise by their address.
			{/if}
		</p>
	{/if}

	<form class="mt-4 flex flex-wrap items-center gap-2" onsubmit={check}>
		<label class="sr-only" for="find-address">Address of a camera</label>
		<input
			id="find-address"
			class="input h-10 min-w-0 flex-1 basis-48"
			bind:value={address}
			placeholder="Check an address, e.g. 192.168.1.20"
			inputmode="url"
			autocomplete="off"
		/>
		<button class="btn-ghost h-10 shrink-0" disabled={checking || !address.trim()}>
			{#if checking}<LoaderCircle class="size-4 animate-spin" />{:else}<Search
					class="size-4"
				/>{/if}Check
		</button>
		{#if checked === 'none'}
			<p class="w-full text-xs text-muted">
				Nothing Norn knows answers there. Pick the type below and enter its details by hand.
			</p>
		{:else if checked === 'error'}
			<p class="w-full text-xs text-danger">{checkError}</p>
		{/if}
	</form>
</section>
