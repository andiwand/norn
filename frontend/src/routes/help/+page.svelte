<script lang="ts">
	// How to reach Norn from elsewhere, and where things are.
	import { store } from '#lib/state.svelte.js';
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';
	import SettingsSection from '#lib/components/SettingsSection.svelte';
	import Webhook from '@lucide/svelte/icons/webhook';
	import FileCode from '@lucide/svelte/icons/file-code';
	import BookOpen from '@lucide/svelte/icons/book-open';
	import Smartphone from '@lucide/svelte/icons/smartphone';
	import InstallApp from '#lib/components/InstallApp.svelte';

	const info = $derived(store.info);
	const origin = $derived(typeof location === 'undefined' ? '' : location.origin);
	const link = 'text-accent hover:underline';
</script>

<svelte:head><title>Help · Norn</title></svelte:head>

<div class="mx-auto max-w-3xl space-y-5">
	<div class="flex items-start gap-2">
		<!-- On phones this page opens from Settings: the way back. -->
		<a href="/settings" class="-ml-2 icon-btn shrink-0 md:hidden" aria-label="Back to Settings"
			><ArrowLeft class="size-5" /></a
		>
		<div>
			<h1 class="page-title">Help</h1>
			<p class="page-intro">Connecting Norn to other things, and where to find more.</p>
		</div>
	</div>

	<div id="install">
		<SettingsSection title="Install the app" icon={Smartphone}>
			<InstallApp />
		</SettingsSection>
	</div>

	<SettingsSection
		title="Webhook"
		description="Start a clip from anything that can send an HTTP request, like Home Assistant or a doorbell. A circle has its own: /api/circles/CIRCLE/record records all its cameras."
		icon={Webhook}
	>
		<div class="p-5">
			<pre
				class="overflow-x-auto rounded-xl bg-surface-2 p-4 font-mono text-xs leading-relaxed">curl -X POST {origin}/api/cameras/<span
					class="text-accent">CAMERA</span
				>/record \
  -H 'Content-Type: application/json' \
  -d '&#123;"trigger": "doorbell", "seconds": 30&#125;'</pre>
			<p class="mt-3 text-xs text-muted">
				Every endpoint: <a class={link} href="/api/docs">API docs</a>.
			</p>
		</div>
	</SettingsSection>

	<SettingsSection
		title="Configuration"
		description="Everything you set in the app is in this file. Edit it by hand too: Norn picks up the change, and the app keeps your comments."
		icon={FileCode}
	>
		<div class="p-5">
			<code class="block overflow-x-auto rounded-xl bg-surface-2 p-3 font-mono text-xs"
				>{info?.config_path ?? '…'}</code
			>
		</div>
	</SettingsSection>

	<SettingsSection title="More" icon={BookOpen}>
		<ul class="space-y-2 p-5 text-sm">
			<li><a class={link} href="https://andiwand.github.io/norn/">Website</a>: what Norn does</li>
			<li>
				<a class={link} href="https://github.com/andiwand/norn#configuration">Configuration</a>:
				every option of config.yaml
			</li>
			<li>
				<a class={link} href="https://github.com/andiwand/norn/issues">Issues</a>: report a problem
				or a camera that doesn't work
			</li>
		</ul>
	</SettingsSection>
</div>
