<script lang="ts">
	let { size = 28, class: className = '' }: { size?: number; class?: string } = $props();
	const id = `logo-${Math.random().toString(36).slice(2, 8)}`;
</script>

<svg width={size} height={size} viewBox="0 0 64 64" class={className} aria-hidden="true">
	<defs>
		<linearGradient {id} x1="0" y1="0" x2="1" y2="1">
			<stop offset="0" stop-color="#a08bff" />
			<stop offset="1" stop-color="#3ee0d0" />
		</linearGradient>
	</defs>
	<path
		d="M5 32c7-12 16-18 27-18s20 6 27 18c-7 12-16 18-27 18S12 44 5 32Z"
		fill="none"
		stroke="url(#{id})"
		stroke-width="4.5"
		stroke-linejoin="round"
	/>
	<path
		d="M12 32c5.5-7.5 12.5-11 20-11"
		fill="none"
		stroke="url(#{id})"
		stroke-width="3"
		stroke-linecap="round"
		opacity=".55"
	/>
	<circle cx="32" cy="32" r="10" fill="none" stroke="url(#{id})" stroke-width="4.5" />
	<circle cx="32" cy="32" r="3.8" fill="currentColor" />
</svg>
