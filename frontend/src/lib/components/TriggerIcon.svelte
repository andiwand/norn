<script lang="ts">
	// An icon for what started a recording.
	import type { Component } from 'svelte';
	import Activity from '@lucide/svelte/icons/activity';
	import User from '@lucide/svelte/icons/user';
	import Car from '@lucide/svelte/icons/car';
	import PawPrint from '@lucide/svelte/icons/paw-print';
	import ScanFace from '@lucide/svelte/icons/scan-face';
	import Package from '@lucide/svelte/icons/package';
	import BellRing from '@lucide/svelte/icons/bell-ring';
	import Hand from '@lucide/svelte/icons/hand';
	import Webhook from '@lucide/svelte/icons/webhook';
	import Image from '@lucide/svelte/icons/image';
	import Video from '@lucide/svelte/icons/video';
	import Zap from '@lucide/svelte/icons/zap';

	let { trigger, class: className = 'size-3.5' }: { trigger: string; class?: string } = $props();

	const icons: Record<string, Component> = {
		motion: Activity,
		person: User,
		vehicle: Car,
		animal: PawPrint,
		face: ScanFace,
		package: Package,
		doorbell: BellRing,
		manual: Hand,
		webhook: Webhook,
		interval: Image,
		continuous: Video
	};
	const Icon = $derived(icons[trigger] ?? Zap);
</script>

<Icon class={className} />
