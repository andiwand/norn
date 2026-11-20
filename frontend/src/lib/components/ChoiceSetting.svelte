<script lang="ts" generics="T extends string | boolean | null">
	// A setting with a few choices, as segmented buttons on the right. With `inherit`, the null
	// choice ("Default") is the value from above, and says which: "Default (Off)".
	let {
		label,
		hint = '',
		value = $bindable(),
		choices,
		inherit,
		disabled = false
	}: {
		label: string;
		hint?: string;
		value: T;
		choices: [T, string][];
		inherit?: T;
		disabled?: boolean;
	} = $props();

	function text(choice: T, name: string): string {
		if (choice !== null || inherit === undefined) return name;
		const from = choices.find(([c]) => c === inherit && c !== null);
		return from ? `${name} (${from[1]})` : name;
	}
</script>

<div class="@container flex flex-wrap items-center justify-between gap-x-6 gap-y-2 px-5 py-3.5">
	<div class="min-w-0 flex-1 basis-56">
		<span class="block text-sm font-medium">{label}</span>
		{#if hint}<span class="mt-0.5 block text-xs text-muted">{hint}</span>{/if}
	</div>
	<div class="flex w-full shrink-0 justify-end @[33rem]:w-60">
		<div
			class="flex max-w-full overflow-x-auto rounded-xl bg-surface-3 p-1 {disabled
				? 'opacity-50'
				: ''}"
			role="radiogroup"
			aria-label={label}
		>
			{#each choices as [choice, name] (String(choice))}
				<button
					type="button"
					role="radio"
					aria-checked={value === choice}
					{disabled}
					class="rounded-lg px-2.5 py-1 text-xs font-medium whitespace-nowrap transition {value ===
					choice
						? 'bg-surface text-text shadow'
						: 'text-muted hover:text-text'}"
					onclick={() => (value = choice)}>{text(choice, name)}</button
				>
			{/each}
		</div>
	</div>
</div>
