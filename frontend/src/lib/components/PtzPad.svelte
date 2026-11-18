<script lang="ts">
	// A d-pad for pan and tilt plus zoom. Hold to move; release to stop, like the camera's own app.
	import { api, type PtzCommand } from '../api';
	import { store } from '../state.svelte';
	import ChevronUp from '@lucide/svelte/icons/chevron-up';
	import ChevronDown from '@lucide/svelte/icons/chevron-down';
	import ChevronLeft from '@lucide/svelte/icons/chevron-left';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import House from '@lucide/svelte/icons/house';
	import ZoomIn from '@lucide/svelte/icons/zoom-in';
	import ZoomOut from '@lucide/svelte/icons/zoom-out';

	let {
		camera,
		speed = 0.5,
		zoom = true
	}: { camera: string; speed?: number; /** Show the zoom buttons. */ zoom?: boolean } = $props();

	let moving = $state<string | null>(null);
	let repeat: ReturnType<typeof setInterval> | undefined;

	// One command after the other: a quick tap must not let its stop overtake its move, or the
	// camera turns on to its end stop.
	let queue: Promise<unknown> = Promise.resolve();
	const send = (command: PtzCommand) =>
		(queue = queue.then(() => store.attempt(() => api.ptz(camera, command))));

	function start(key: string, pan = 0, tilt = 0, zoom = 0) {
		moving = key;
		const command: PtzCommand = {
			action: 'move',
			pan: pan * speed,
			tilt: tilt * speed,
			zoom: zoom * speed
		};
		send(command);
		// The server stops a move it doesn't hear about for a while; holding renews it.
		clearInterval(repeat);
		repeat = setInterval(() => send(command), 3000);
	}

	function stop() {
		clearInterval(repeat);
		if (!moving) return;
		moving = null;
		send({ action: 'stop' });
	}

	// Leaving the window, the tab or the page while holding: stop.
	$effect(() => {
		const onHide = () => stop();
		const onVisibility = () => document.hidden && stop();
		window.addEventListener('blur', onHide);
		window.addEventListener('pagehide', onHide);
		document.addEventListener('visibilitychange', onVisibility);
		return () => {
			stop();
			window.removeEventListener('blur', onHide);
			window.removeEventListener('pagehide', onHide);
			document.removeEventListener('visibilitychange', onVisibility);
		};
	});

	// Pointer events cover mouse and touch; capture keeps the release on the button that started.
	// From the keyboard, Enter or Space held on a focused button moves the same way.
	function hold(node: HTMLElement, args: [string, number, number, number]) {
		let current = args;
		const down = (e: PointerEvent) => {
			node.setPointerCapture(e.pointerId);
			start(...current);
		};
		const press = (e: KeyboardEvent) => e.key === 'Enter' || e.key === ' ';
		const keydown = (e: KeyboardEvent) => {
			if (!press(e)) return;
			e.preventDefault();
			if (!e.repeat) start(...current);
		};
		const keyup = (e: KeyboardEvent) => {
			if (!press(e)) return;
			e.preventDefault();
			stop();
		};
		const stops = ['pointerup', 'pointercancel', 'lostpointercapture', 'blur'] as const;
		node.addEventListener('pointerdown', down);
		node.addEventListener('keydown', keydown);
		node.addEventListener('keyup', keyup);
		for (const type of stops) node.addEventListener(type, stop);
		return {
			update(next: [string, number, number, number]) {
				current = next;
			},
			destroy() {
				node.removeEventListener('pointerdown', down);
				node.removeEventListener('keydown', keydown);
				node.removeEventListener('keyup', keyup);
				for (const type of stops) node.removeEventListener(type, stop);
			}
		};
	}

	const keys: Record<string, [string, number, number, number]> = {
		ArrowUp: ['up', 0, 1, 0],
		ArrowDown: ['down', 0, -1, 0],
		ArrowLeft: ['left', -1, 0, 0],
		ArrowRight: ['right', 1, 0, 0],
		'+': ['in', 0, 0, 1],
		'=': ['in', 0, 0, 1],
		'-': ['out', 0, 0, -1]
	};

	function onkeydown(e: KeyboardEvent) {
		const target = e.target as HTMLElement;
		if (target.closest('input, select, textarea') || e.repeat) return;
		// Only while the mouse is over the video or the pad: elsewhere the keys scroll the page.
		if (!document.querySelector('[data-ptz-keys]:hover')) return;
		const args = keys[e.key];
		if (args && (zoom || !args[3])) {
			e.preventDefault();
			start(...args);
		}
	}
	function onkeyup(e: KeyboardEvent) {
		if (keys[e.key]) stop();
	}

	const pad =
		'absolute grid size-12 place-items-center rounded-full text-text/80 transition hover:bg-surface-3 hover:text-text active:scale-95 touch-none';
	const on = 'bg-accent/20 text-accent';
</script>

<svelte:window {onkeydown} {onkeyup} />

<div data-ptz-keys class="flex items-center justify-center gap-6">
	<div
		class="relative size-44 rounded-full border border-line bg-gradient-to-b from-surface-2 to-surface shadow-inner"
		role="group"
		aria-label="Pan and tilt"
	>
		<button
			class="{pad} top-1.5 left-1/2 -translate-x-1/2 {moving === 'up' ? on : ''}"
			use:hold={['up', 0, 1, 0]}
			aria-label="Tilt up"
		>
			<ChevronUp class="size-6" />
		</button>
		<button
			class="{pad} bottom-1.5 left-1/2 -translate-x-1/2 {moving === 'down' ? on : ''}"
			use:hold={['down', 0, -1, 0]}
			aria-label="Tilt down"
		>
			<ChevronDown class="size-6" />
		</button>
		<button
			class="{pad} top-1/2 left-1.5 -translate-y-1/2 {moving === 'left' ? on : ''}"
			use:hold={['left', -1, 0, 0]}
			aria-label="Pan left"
		>
			<ChevronLeft class="size-6" />
		</button>
		<button
			class="{pad} top-1/2 right-1.5 -translate-y-1/2 {moving === 'right' ? on : ''}"
			use:hold={['right', 1, 0, 0]}
			aria-label="Pan right"
		>
			<ChevronRight class="size-6" />
		</button>
		<button
			class="absolute top-1/2 left-1/2 grid size-14 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full border border-line-strong bg-surface-3 text-muted transition hover:text-text active:scale-95"
			onclick={() => send({ action: 'home' })}
			aria-label="Home position"
			title="Home"
		>
			<House class="size-5" />
		</button>
	</div>

	{#if zoom}<div
			class="flex flex-col gap-2 rounded-full border border-line bg-surface-2 p-1.5"
			role="group"
			aria-label="Zoom"
		>
			<button
				class="grid size-12 touch-none place-items-center rounded-full transition hover:bg-surface-3 {moving ===
				'in'
					? on
					: ''}"
				use:hold={['in', 0, 0, 1]}
				aria-label="Zoom in"
			>
				<ZoomIn class="size-5" />
			</button>
			<button
				class="grid size-12 touch-none place-items-center rounded-full transition hover:bg-surface-3 {moving ===
				'out'
					? on
					: ''}"
				use:hold={['out', 0, 0, -1]}
				aria-label="Zoom out"
			>
				<ZoomOut class="size-5" />
			</button>
		</div>{/if}
</div>
