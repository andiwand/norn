<script lang="ts">
	// One text setting: label and hint on the left, the text field on the right.
	let {
		label,
		hint = '',
		value = $bindable(),
		placeholder = '',
		type = 'text',
		fallback
	}: {
		label: string;
		hint?: string;
		value: string;
		placeholder?: string;
		type?: 'text' | 'password';
		/** The default, mentioned when the value differs from it. */
		fallback?: string;
	} = $props();

	const id = $props.id();
	const differs = $derived(fallback !== undefined && fallback !== value);
</script>

<div class="@container flex flex-wrap items-center justify-between gap-x-6 gap-y-2 px-5 py-3.5">
	<label for={id} class="min-w-0 flex-1 basis-56">
		<span class="block text-sm font-medium">{label}</span>
		{#if hint || differs}
			<span class="mt-0.5 block text-xs text-muted">
				{hint}{#if differs}
					{hint ? ' ' : ''}Default: {fallback || 'none'}.{/if}
			</span>
		{/if}
	</label>
	<div class="flex w-full shrink-0 justify-end @[33rem]:w-60">
		<input
			{id}
			{type}
			class="input w-full font-mono text-[13px] @[33rem]:w-60"
			bind:value
			{placeholder}
			autocomplete={type === 'password' ? 'new-password' : 'off'}
			spellcheck="false"
		/>
	</div>
</div>
