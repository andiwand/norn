// See https://svelte.dev/docs/kit/types#app.d.ts
import type { HTMLAttributes } from 'svelte/elements';

declare global {
	namespace App {
		// interface Error {}
		// interface Locals {}
		// interface PageData {}
		// interface PageState {}
		// interface Platform {}
	}
}

declare module 'svelte/elements' {
	interface SvelteHTMLElements {
		// The live player of lib/go2rtc/norn-video.js.
		'norn-video': HTMLAttributes<HTMLElement> & {
			fit?: 'contain' | 'cover';
			'onnorn-state'?: (event: Event) => void;
			'onnorn-mode'?: (event: Event) => void;
			'onnorn-error'?: (event: Event) => void;
		};
	}
}

export {};
