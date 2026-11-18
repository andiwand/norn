// The icons drivers may name for their controls (Control.icon). A control with an icon is one
// people use often: the camera page also offers it under the video.
import type { Component } from 'svelte';
import Moon from '@lucide/svelte/icons/moon';
import Sun from '@lucide/svelte/icons/sun';
import Lamp from '@lucide/svelte/icons/lamp';
import Siren from '@lucide/svelte/icons/siren';
import Activity from '@lucide/svelte/icons/activity';
import EyeOff from '@lucide/svelte/icons/eye-off';
import Bell from '@lucide/svelte/icons/bell';
import Volume2 from '@lucide/svelte/icons/volume-2';
import Settings2 from '@lucide/svelte/icons/settings-2';
import ScanEye from '@lucide/svelte/icons/scan-eye';
import Timer from '@lucide/svelte/icons/timer';

const icons: Record<string, Component> = {
	moon: Moon,
	sun: Sun,
	lamp: Lamp,
	siren: Siren,
	activity: Activity,
	'eye-off': EyeOff,
	bell: Bell,
	volume: Volume2,
	'scan-eye': ScanEye,
	timer: Timer
};

export function controlIcon(name: string | null | undefined): Component {
	return icons[name ?? ''] ?? Settings2;
}

/** Controls for the row under the video: switches and choices with an icon, not network
 * settings. Sliders, buttons (a siren!) and the rest stay in the settings. */
export function isQuick(c: { kind: string; icon?: string | null; group: string }): boolean {
	return !!c.icon && (c.kind === 'toggle' || c.kind === 'select') && c.group !== 'Network';
}
