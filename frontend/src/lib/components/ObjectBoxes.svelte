<script lang="ts">
	// Boxes around what Norn's AI found on a still, with how sure it is: solid when it starts
	// clips, dashed when Norn ignores it (seen too briefly yet, or not moving: a parked car, a
	// sheet on a chair). Over live video (DetectionOverlay) and recordings (RecordingDialog);
	// the parent sizes this to the picture.
	import type { SeenObject } from '../api';
	import { triggerLabel } from '../format';

	let { objects }: { objects: SeenObject[] } = $props();

	const why = { counts: '', unconfirmed: 'checking', still: 'ignored: not moving' };
</script>

<div class="pointer-events-none absolute inset-0" aria-hidden="true">
	{#each objects as o, i (i)}
		{@const [x1, y1, x2, y2] = o.box}
		<div
			class="absolute rounded-md border-2 {o.status === 'counts'
				? 'border-warning'
				: 'border-dashed border-white/70'}"
			style="left:{x1 * 100}%;top:{y1 * 100}%;width:{(x2 - x1) * 100}%;height:{(y2 - y1) * 100}%"
		>
			<span
				class="absolute top-0.5 left-0.5 max-w-[calc(100%-4px)] truncate rounded px-1.5 py-px text-[10px] leading-4 font-semibold whitespace-nowrap {o.status ===
				'counts'
					? 'bg-warning text-black'
					: 'bg-black/70 text-white'}"
			>
				{triggerLabel(o.kind)}
				{Math.round(o.score * 100)}%{why[o.status] ? ` · ${why[o.status]}` : ''}
			</span>
		</div>
	{/each}
</div>
