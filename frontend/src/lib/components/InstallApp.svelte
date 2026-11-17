<script lang="ts">
	// Install Norn as an app: the browser's own dialog where there is one, else how to do it.
	import { install } from '../install.svelte';
	import Download from '@lucide/svelte/icons/download';
</script>

<div class="flex flex-wrap items-center gap-3 p-5 text-sm">
	{#if install.installed}
		<p class="text-muted">Norn runs as an installed app here.</p>
	{:else if install.offered}
		<p class="min-w-0 flex-1 basis-60 text-muted">
			Its own icon, full screen, without the browser's bars.
		</p>
		<button class="btn-primary" onclick={() => install.install()}
			><Download class="size-4" />Install</button
		>
	{:else}
		<p class="text-muted">{install.hint}</p>
	{/if}
</div>
