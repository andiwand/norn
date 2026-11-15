<script lang="ts">
	let { mode = 'clip' }: { mode?: 'clip' | 'continuous' } = $props();
</script>

<span
	class="inline-flex items-center gap-1.5 rounded-full bg-black/55 px-2.5 py-1 text-[11px] font-semibold tracking-wide text-white backdrop-blur-md"
	title={mode === 'continuous' ? 'Recording continuously' : 'Recording a clip'}
>
	<span class="rec-dot size-2 rounded-full bg-danger"></span>
	REC
</span>
